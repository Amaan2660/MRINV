import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import date
from fpdf import FPDF
from PIL import Image
import os

st.set_page_config(page_title="MR Fakturagenerator", layout="centered")

# ----- Tilføj baggrund og container -----
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

img.logo {
    position: absolute;
    top: 10px;
    left: 10px;
    width: 60px;
}
</style>
"""

st.markdown(page_bg, unsafe_allow_html=True)

# Logo
st.image("logo.png", width=80)

# ----- Funktioner -----
def rens_data(df):
    df = df[~df.astype(str).apply(lambda x: x.str.contains("DitVikar|ditvikar|Dit vikarbureau", case=False)).any(axis=1)]
    kolonner = ["Dato", "Medarbejder", "Starttid", "Sluttid", "Timer", "Personalegruppe", "Jobfunktion", "Shift status"]
    df = df[kolonner]
    df = df[df["Timer"].notna() & (df["Timer"] > 0)]
    df["Tid"] = df["Starttid"].astype(str).str[:5] + "-" + df["Sluttid"].astype(str).str[:5]
    # Keep original jobfunktion before bucketing to city
    df["Jobfunktion_raw"] = df["Jobfunktion"]
    df["Dato"] = pd.to_datetime(df["Dato"], format="%d.%m.%Y")

    byer = ["allerød", "egedal", "frederiksund", "solrød", "herlev", "ringsted", "køge"]
    def find_by(jobfunktion):
        jf = str(jobfunktion).lower()
        for by in byer:
            if by in jf:
                return "frederiksund" if by == "frederikssund" else by
        return "andet"
    df["Jobfunktion"] = df["Jobfunktion"].apply(find_by)

    df = df.sort_values(by=["Jobfunktion", "Dato", "Starttid"])
    return df

def beregn_takst(row):
    helligdag = row["Helligdag"] == "Ja"
    personale = row["Personale"].lower()
    starttid = row["Tidsperiode"].split("-")[0]
    start_hour = int(starttid.split(":")[0])
    dagtid = start_hour < 15
    ugedag = row["Dato"].weekday()

    if helligdag:
        if personale == "ufaglært": return 215 if dagtid else 220
        if personale == "hjælper": return 215 if dagtid else 220
        if personale == "assistent": return 230 if dagtid else 240
    else:
        weekend = ugedag >= 5
        if personale == "ufaglært":
            return 215 if weekend and dagtid else 220 if weekend else 175 if dagtid else 210
        if personale == "hjælper":
            return 215 if weekend and dagtid else 220 if weekend else 200 if dagtid else 210
        if personale == "assistent":
            return 230 if weekend and dagtid else 240 if weekend else 220 if dagtid else 225
    return 0

def generer_faktura(df, fakturanummer, helligdage_valgte):
    invoice_df = df.copy()
    invoice_df["Helligdag"] = invoice_df["Dato"].isin(helligdage_valgte).map({True: "Ja", False: "Nej"})
    invoice_df = invoice_df.rename(columns={"Tid": "Tidsperiode", "Personalegruppe": "Personale"})
    invoice_df["Takst"] = invoice_df.apply(beregn_takst, axis=1)
    # +10 kr/time when original jobfunktion mentions "Kirsten Rute"   
    invoice_df.loc[invoice_df["Jobfunktion_raw"].astype(str).str.contains(r"\bkirsten\s+rute\b", case=False, na=False),"Takst"] += 10
    invoice_df["Samlet"] = invoice_df["Timer"] * invoice_df["Takst"]
    invoice_df = invoice_df[[
        "Dato", "Medarbejder", "Tidsperiode", "Timer", "Personale",
        "Jobfunktion", "Helligdag", "Takst", "Samlet"]]

    invoice_df = invoice_df.sort_values(by=["Jobfunktion", "Dato", "Tidsperiode"])
    uge_nr = invoice_df['Dato'].dt.isocalendar().week.min()
    output_xlsx = BytesIO()
    filename_xlsx = f"FAKTURA ({fakturanummer}) FOR UGE {uge_nr} til AJOUR CARE FRA AKUTVIKAR.xlsx"
    invoice_df.to_excel(output_xlsx, index=False, sheet_name="Faktura")
    output_xlsx.seek(0)

    output_pdf = BytesIO()
    pdf = FPDF(unit='mm', format='A4')
    pdf.add_page()

    logo_path = "logo.png"
    if os.path.exists(logo_path):
        pdf.image(logo_path, x=10, y=2, w=30)

    pdf.set_xy(150, 6)
    pdf.set_font("Arial", "B", 20)
    pdf.cell(50, 10, f"INVOICE {fakturanummer}", ln=False)

    pdf.ln(32)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(95, 6, "Fra: MR Rekruttering", ln=0)
    pdf.cell(95, 6, "Til: Ajour Care ApS", ln=1)

    pdf.set_font("Arial", "", 10)
    pdf.cell(95, 6, "Valbygårdsvej 1, 4. th, 2500 Valby", ln=0)
    pdf.cell(95, 6, "CVR: 34478953", ln=1)
    pdf.cell(95, 6, "CVR.nr. 45090965", ln=0)
    pdf.cell(95, 6, "Kontakt: Charlotte Bigum Christensen", ln=1)
    pdf.cell(95, 6, "Tlf: 71747290", ln=0)
    pdf.cell(95, 6, "Email: cbc@ajourcare.dk", ln=1)
    pdf.cell(95, 6, "Web: www.akutvikar.com", ln=0)
    pdf.ln(12)

    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 6, f"Fakturadato: {date.today().strftime('%d.%m.%Y')}", ln=True)
    pdf.ln(6)

    col_widths = [20, 32, 25, 12, 24, 22, 18, 12, 20]
    headers = ["Dato", "Medarbejder", "Tidsperiode", "Timer", "Personale", "Jobfunktion", "Helligdag", "Takst", "Samlet"]
    pdf.set_font("Arial", "B", 10)
    pdf.set_x(10)
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, border=1)
    pdf.ln()

    pdf.set_font("Arial", "", 9)
    total = 0
    for _, row in invoice_df.iterrows():
        values = [
            row["Dato"].strftime("%d.%m.%Y"), row["Medarbejder"], row["Tidsperiode"], f"{row['Timer']:.1f}",
            row["Personale"], row["Jobfunktion"], row["Helligdag"], f"{row['Takst']}", f"{row['Samlet']:.2f}"
        ]
        total += row["Samlet"]
        pdf.set_x(10)
        for i, v in enumerate(values):
            pdf.cell(col_widths[i], 8, str(v), border=1)
        pdf.ln()

    pdf.ln(4)
    moms = total * 0.25
    total_med_moms = total + moms
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 8, f"Subtotal: {total:.2f} kr", ln=True)
    pdf.cell(0, 8, f"Moms (25%): {moms:.2f} kr", ln=True)
    pdf.cell(0, 8, f"Total inkl. moms: {total_med_moms:.2f} kr", ln=True)

    pdf.ln(5)
    pdf.set_font("Arial", "", 9)
    pdf.cell(0, 6, "Bank: Finseta | IBAN: GB79TCCL04140404627601 | BIC: TCCLGB3LXXX", ln=True)
    pdf.cell(0, 6, "Betalingsbetingelser: Bankoverførsel. Fakturanr. bedes angivet ved betaling.", ln=True)

    pdf_output = pdf.output(dest='S').encode('latin-1')
    output_pdf = BytesIO(pdf_output)
    filename_pdf = f"FAKTURA ({fakturanummer}) FOR UGE {uge_nr} til AJOUR CARE FRA AKUTVIKAR.pdf"

    return output_xlsx, filename_xlsx, output_pdf, filename_pdf

# ----- Streamlit UI -----
st.title("MR Rekruttering – Fakturagenerator")

uploaded_file = st.file_uploader("Upload vagtplan-fil (Excel)", type=["xlsx"])
fakturanr = st.number_input("Fakturanummer", min_value=1, step=1)

if uploaded_file and fakturanr:
    df = pd.read_excel(uploaded_file, sheet_name=None)
    sheet = list(df.keys())[0]
    raw_df = df[sheet]
    renset_df = rens_data(raw_df)

    unikke_datoer = sorted(renset_df["Dato"].dt.date.unique())
    helligdage_valgte = st.multiselect("Vælg helligdage blandt datoerne i filen", options=unikke_datoer)
    helligdage_valgte = [pd.Timestamp(d) for d in helligdage_valgte]

    if st.button("Generer faktura"):
        output_xlsx, filename_xlsx, output_pdf, filename_pdf = generer_faktura(renset_df, fakturanr, helligdage_valgte)
        st.success("Faktura klar som Excel og PDF!")
        st.download_button("Download Excel", data=output_xlsx, file_name=filename_xlsx)
        st.download_button("Download PDF", data=output_pdf, file_name=filename_pdf)
