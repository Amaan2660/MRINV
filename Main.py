import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import date
from fpdf import FPDF
import os

st.set_page_config(page_title="MR Fakturagenerator", layout="centered")

# ----- Styling -----
page_bg = """
<style>
body {
    background-color: #aa1e1e;
    color: white;
}
[data-testid="stAppViewContainer"] > .main {
    background-color: white;
    color: black;
    border-radius: 10px;
    padding: 2rem;
    box-shadow: 0 0 10px rgba(0,0,0,0.3);
    margin-top: 2rem;
    max-width: 900px;
    margin-left: auto;
    margin-right: auto;
}
</style>
"""
st.markdown(page_bg, unsafe_allow_html=True)

st.image("logo.png", width=80)

# ----- Data rens -----
def rens_data(df):
    df = df[
        ~df.astype(str)
        .apply(lambda x: x.str.contains("DitVikar|ditvikar|Dit vikarbureau", case=False))
        .any(axis=1)
    ]

    kolonner = [
        "Dato", "Medarbejder", "Starttid", "Sluttid",
        "Timer", "Personalegruppe", "Jobfunktion", "Shift status"
    ]
    df = df[kolonner]
    df = df[df["Timer"].notna() & (df["Timer"] > 0)]

    df["Tid"] = df["Starttid"].astype(str).str[:5] + "-" + df["Sluttid"].astype(str).str[:5]
    df["Jobfunktion_raw"] = df["Jobfunktion"]

    df["Dato"] = pd.to_datetime(df["Dato"], format="%d.%m.%Y")

    byer = ["allerød", "egedal", "frederiksund", "solrød", "herlev", "ringsted"]

    def find_by(jobfunktion):
        jf = str(jobfunktion).lower()
        for by in byer:
            if by in jf:
                return "frederiksund" if by == "frederikssund" else by
        return "andet"

    df["Jobfunktion"] = df["Jobfunktion"].apply(find_by)
    df = df.sort_values(by=["Jobfunktion", "Dato", "Starttid"])
    return df

# ----- Takstberegning -----
def beregn_takst(row):
    helligdag = row["Helligdag"] == "Ja"
    personale = str(row["Personale"]).strip().lower()
    start_hour = int(row["Tidsperiode"].split("-")[0].split(":")[0])
    dagtid = start_hour < 15
    ugedag = row["Dato"].weekday()

    if helligdag:
        if personale in ["ufaglært", "hjælper"]:
            return 215 if dagtid else 220
        if personale == "assistent":
            return 230 if dagtid else 240
    else:
        weekend = ugedag >= 5
        if personale == "ufaglært":
            return 215 if weekend and dagtid else 220 if weekend else 175 if dagtid else 210
        if personale == "hjælper":
            return 215 if weekend and dagtid else 220 if weekend else 200 if dagtid else 210
        if personale == "assistent":
            return 230 if weekend and dagtid else 240 if weekend else 220 if dagtid else 225
    return 0

# ----- Faktura -----
def generer_faktura(df, fakturanummer, helligdage_valgte):
    invoice_df = df.copy()
    invoice_df["Helligdag"] = invoice_df["Dato"].isin(helligdage_valgte).map({True: "Ja", False: "Nej"})
    invoice_df = invoice_df.rename(columns={"Tid": "Tidsperiode", "Personalegruppe": "Personale"})

    # ✅ Normaliser personale (Assistent 2 → Assistent)
    invoice_df["Personale"] = (
        invoice_df["Personale"]
        .astype(str)
        .str.lower()
        .replace({"assistent 2": "assistent"})
    )

    invoice_df["Takst"] = invoice_df.apply(beregn_takst, axis=1)

    # ✅ +10 kr/time hvis Jobfunktion indeholder "Kirsten" (alle placeringer)
    invoice_df.loc[
        invoice_df["Jobfunktion_raw"]
        .astype(str)
        .str.contains(r"\bkirsten\b", case=False, na=False),
        "Takst"
    ] += 10

    invoice_df["Samlet"] = invoice_df["Timer"] * invoice_df["Takst"]

    invoice_df = invoice_df[
        ["Dato", "Medarbejder", "Tidsperiode", "Timer", "Personale",
         "Jobfunktion", "Helligdag", "Takst", "Samlet"]
    ]

    invoice_df = invoice_df.sort_values(by=["Jobfunktion", "Dato", "Tidsperiode"])
    uge_nr = invoice_df["Dato"].dt.isocalendar().week.min()

    # ----- Excel -----
    output_xlsx = BytesIO()
    filename_xlsx = f"FAKTURA ({fakturanummer}) FOR UGE {uge_nr}.xlsx"
    invoice_df.to_excel(output_xlsx, index=False)
    output_xlsx.seek(0)

    # ----- PDF -----
    pdf = FPDF()
    pdf.add_page()

    if os.path.exists("logo.png"):
        pdf.image("logo.png", x=10, y=5, w=30)

    pdf.set_xy(140, 10)
    pdf.set_font("Arial", "B", 18)
    pdf.cell(60, 10, f"INVOICE {fakturanummer}")

    pdf.ln(30)
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 6, f"Fakturadato: {date.today().strftime('%d.%m.%Y')}", ln=True)
    pdf.ln(4)

    headers = invoice_df.columns.tolist()
    widths = [20, 32, 25, 12, 24, 22, 18, 12, 20]

    pdf.set_font("Arial", "B", 9)
    for h, w in zip(headers, widths):
        pdf.cell(w, 8, h, border=1)
    pdf.ln()

    pdf.set_font("Arial", "", 9)
    total = 0
    for _, r in invoice_df.iterrows():
        values = [
            r["Dato"].strftime("%d.%m.%Y"),
            r["Medarbejder"],
            r["Tidsperiode"],
            f"{r['Timer']:.1f}",
            r["Personale"],
            r["Jobfunktion"],
            r["Helligdag"],
            f"{r['Takst']}",
            f"{r['Samlet']:.2f}",
        ]
        total += r["Samlet"]
        for v, w in zip(values, widths):
            pdf.cell(w, 8, str(v), border=1)
        pdf.ln()

    moms = total * 0.25
    pdf.ln(4)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 6, f"Subtotal: {total:.2f} kr", ln=True)
    pdf.cell(0, 6, f"Moms (25%): {moms:.2f} kr", ln=True)
    pdf.cell(0, 6, f"Total inkl. moms: {total + moms:.2f} kr", ln=True)

    pdf_bytes = pdf.output(dest="S").encode("latin-1")
    output_pdf = BytesIO(pdf_bytes)
    filename_pdf = f"FAKTURA ({fakturanummer}) FOR UGE {uge_nr}.pdf"

    return output_xlsx, filename_xlsx, output_pdf, filename_pdf

# ----- UI -----
st.title("MR Rekruttering – Fakturagenerator")

uploaded_file = st.file_uploader("Upload vagtplan (Excel)", type=["xlsx"])
fakturanr = st.number_input("Fakturanummer", min_value=1, step=1)

if uploaded_file and fakturanr:
    raw_df = pd.read_excel(uploaded_file)
    renset_df = rens_data(raw_df)

    unikke_datoer = sorted(renset_df["Dato"].dt.date.unique())
    helligdage = st.multiselect("Vælg helligdage", unikke_datoer)
    helligdage = [pd.Timestamp(d) for d in helligdage]

    if st.button("Generer faktura"):
        xlsx, xlsx_name, pdf, pdf_name = generer_faktura(renset_df, fakturanr, helligdage)
        st.success("Faktura genereret")
        st.download_button("Download Excel", xlsx, file_name=xlsx_name)
        st.download_button("Download PDF", pdf, file_name=pdf_name)
