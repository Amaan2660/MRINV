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
body { background-color: #aa1e1e; color: white; }
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

if os.path.exists("logo.png"):
    st.image("logo.png", width=80)

# --------------------------------------------------
# DATA CLEANING
# --------------------------------------------------
def rens_data(df):
    df = df[
        ~df.astype(str)
        .apply(lambda x: x.str.contains("DitVikar|ditvikar|Dit vikarbureau", case=False, na=False))
        .any(axis=1)
    ]

    df = df[
        ["Dato","Medarbejder","Starttid","Sluttid",
         "Timer","Personalegruppe","Jobfunktion","Shift status"]
    ]

    df = df[df["Timer"].notna() & (df["Timer"] > 0)]

    df["Tid"] = df["Starttid"].astype(str).str[:5] + "-" + df["Sluttid"].astype(str).str[:5]
    df["Jobfunktion_raw"] = df["Jobfunktion"]
    df["Dato"] = pd.to_datetime(df["Dato"], format="%d.%m.%Y")

    byer = ["allerød","egedal","frederiksund","solrød","herlev","ringsted","køge"]

    def find_by(jobfunktion):
        jf = str(jobfunktion).lower()
        for by in byer:
            if by in jf:
                return by
        return "andet"

    df["Jobfunktion"] = df["Jobfunktion"].apply(find_by)
    return df.sort_values(by=["Jobfunktion","Dato","Starttid"])

# --------------------------------------------------
# RATE LOGIC
# --------------------------------------------------
def beregn_takst(row):
    helligdag = row["Helligdag"] == "Ja"
    personale = row["Personale"]

    start_hour = int(row["Tidsperiode"].split("-")[0][:2])
    dag = start_hour < 15
    weekend = row["Dato"].weekday() >= 5

    if personale == "ufaglært":
        if helligdag: return 215 if dag else 220
        return 215 if weekend and dag else 220 if weekend else 175 if dag else 210

    if personale == "hjælper":
        if helligdag: return 215 if dag else 220
        return 215 if weekend and dag else 220 if weekend else 200 if dag else 210

    if personale == "assistent":
        if helligdag: return 230 if dag else 240
        return 230 if weekend and dag else 240 if weekend else 220 if dag else 225

    return 0

# --------------------------------------------------
# INVOICE GENERATION
# --------------------------------------------------
def generer_faktura(df, fakturanummer, helligdage):
    inv = df.copy()

    inv["Helligdag"] = inv["Dato"].isin(helligdage).map({True:"Ja", False:"Nej"})
    inv = inv.rename(columns={"Tid":"Tidsperiode","Personalegruppe":"Personale"})

    # Normalize personnel
    inv["Personale"] = (
        inv["Personale"]
        .astype(str)
        .str.replace("\u00A0"," ", regex=False)
        .str.replace(r"\s+"," ", regex=True)
        .str.strip()
        .str.lower()
    )
    inv.loc[inv["Personale"] == "assistent 2", "Personale"] = "assistent"

    # Rates
    inv["Takst"] = [beregn_takst(r) for _, r in inv.iterrows()]

    # Kirsten +10
    inv.loc[
        inv["Jobfunktion_raw"].astype(str).str.contains("kirsten", case=False, na=False),
        "Takst"
    ] += 10

    inv["Samlet"] = inv["Timer"] * inv["Takst"]

    inv = inv[
        ["Dato","Medarbejder","Tidsperiode","Timer",
         "Personale","Jobfunktion","Helligdag","Takst","Samlet"]
    ]

    uge = inv["Dato"].dt.isocalendar().week.min()

    # ---------------- Excel ----------------
    excel = BytesIO()
    inv.to_excel(excel, index=False)
    excel.seek(0)

    # ---------------- PDF ----------------
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Logo
    if os.path.exists("logo.png"):
        pdf.image("logo.png", 10, 5, 30)

    # ----- HEADER -----
    pdf.set_font("Arial","B",12)

    pdf.set_xy(10,20)
    pdf.cell(95,6,"Fra: MR Rekruttering",ln=1)
    pdf.set_font("Arial","",10)
    pdf.set_x(10); pdf.cell(95,6,"Valbygårdsvej 1, 4. th, 2500 Valby",ln=1)
    pdf.set_x(10); pdf.cell(95,6,"CVR.nr. 45090965",ln=1)
    pdf.set_x(10); pdf.cell(95,6,"Tlf: 71747290",ln=1)
    pdf.set_x(10); pdf.cell(95,6,"Web: www.akutvikar.com",ln=1)

    pdf.set_font("Arial","B",12)
    pdf.set_xy(105,20)
    pdf.cell(95,6,"Til: Ajour Care ApS",ln=1)
    pdf.set_font("Arial","",10)
    pdf.set_x(105); pdf.cell(95,6,"CVR: 34478953",ln=1)
    pdf.set_x(105); pdf.cell(95,6,"Kontakt: Charlotte Bigum Christensen",ln=1)
    pdf.set_x(105); pdf.cell(95,6,"Email: cbc@ajourcare.dk",ln=1)

    pdf.ln(6)
    pdf.set_x(10)
    pdf.cell(0,6,f"Fakturadato: {date.today().strftime('%d.%m.%Y')}",ln=1)
    pdf.ln(6)

    # ----- TABLE -----
    widths = [18,38,24,10,18,20,20,12,16]

    pdf.set_font("Arial","B",9)
    pdf.set_x(10)
    for h,w in zip(inv.columns, widths):
        pdf.cell(w,8,h,1)
    pdf.ln()

    pdf.set_font("Arial","",9)
    total = 0
    for _, r in inv.iterrows():
        pdf.set_x(10)
        row = [
            r["Dato"].strftime("%d.%m.%Y"),
            r["Medarbejder"],
            r["Tidsperiode"],
            f"{r['Timer']:.1f}",
            r["Personale"],
            r["Jobfunktion"],
            r["Helligdag"],
            str(int(r["Takst"])),
            f"{r['Samlet']:.2f}"
        ]
        for v,w in zip(row, widths):
            pdf.cell(w,8,str(v),1)
        pdf.ln()
        total += r["Samlet"]

    moms = total * 0.25
    pdf.ln(5)
    pdf.set_font("Arial","B",10)
    pdf.cell(0,6,f"Subtotal: {total:.2f} kr",ln=1)
    pdf.cell(0,6,f"Moms (25%): {moms:.2f} kr",ln=1)
    pdf.cell(0,6,f"Total inkl. moms: {total+moms:.2f} kr",ln=1)

    # ----- FOOTER -----
    pdf.ln(6)
    pdf.set_font("Arial","",9)
    pdf.cell(0,6,"Bank: Finseta | IBAN: GB79TCCL04140404627601 | BIC: TCCLGB3LXXX",ln=1)
    pdf.cell(0,6,"Betalingsbetingelser: Bankoverførsel. Fakturanr. bedes angivet ved betaling.",ln=1)

    pdf_bytes = pdf.output(dest="S").encode("latin-1")

    return excel, f"FAKTURA_{fakturanummer}_UGE_{uge}.xlsx", BytesIO(pdf_bytes), f"FAKTURA_{fakturanummer}_UGE_{uge}.pdf"

# --------------------------------------------------
# UI
# --------------------------------------------------
st.title("MR Rekruttering – Fakturagenerator")

file = st.file_uploader("Upload vagtplan-fil (Excel)", type=["xlsx"])
fakturanr = st.number_input("Fakturanummer", min_value=1, step=1)

if file and fakturanr:
    raw = pd.read_excel(file)
    clean = rens_data(raw)

    dates = sorted(clean["Dato"].dt.date.unique())
    helligdage = [pd.Timestamp(d) for d in st.multiselect("Vælg helligdage", dates)]

    if st.button("Generer faktura"):
        xls, xls_name, pdf, pdf_name = generer_faktura(clean, fakturanr, helligdage)
        st.success("Faktura klar")
        st.download_button("Download Excel", xls, file_name=xls_name)
        st.download_button("Download PDF", pdf, file_name=pdf_name)


