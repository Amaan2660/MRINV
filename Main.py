import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import date
from fpdf import FPDF
import os

# --------------------------------------------------
# PAGE SETUP
# --------------------------------------------------
st.set_page_config(page_title="MR Fakturagenerator", layout="centered")

st.markdown("""
<style>
body { background-color:#aa1e1e; }
[data-testid="stAppViewContainer"] > .main {
    background:white;
    border-radius:10px;
    padding:2rem;
    max-width:900px;
    margin:auto;
}
</style>
""", unsafe_allow_html=True)

if os.path.exists("logo.png"):
    st.image("logo.png", width=80)

# --------------------------------------------------
# DATA CLEANING
# --------------------------------------------------
def rens_data(df):
    df = df[
        ~df.astype(str)
        .apply(lambda x: x.str.contains("DitVikar", case=False, na=False))
        .any(axis=1)
    ]

    df = df[
        ["Dato","Medarbejder","Starttid","Sluttid","Timer",
         "Personalegruppe","Jobfunktion","Shift status"]
    ]

    df = df[df["Timer"].notna() & (df["Timer"] > 0)]

    df["Tid"] = df["Starttid"].astype(str).str[:5] + "-" + df["Sluttid"].astype(str).str[:5]
    df["Jobfunktion_raw"] = df["Jobfunktion"]
    df["Dato"] = pd.to_datetime(df["Dato"], format="%d.%m.%Y")

    return df.sort_values(["Dato","Starttid"])

# --------------------------------------------------
# RATE LOGIC (100% SAFE)
# --------------------------------------------------
def beregn_takst(row):
    personale = str(row["Personale"]).strip().lower()

    # Only Assistant / Assistant 2 allowed
    if personale not in ("assistent", "assistent 2"):
        return 0

    helligdag = row["Helligdag"] == "Ja"
    start_hour = int(row["Tidsperiode"][:2])
    dag = start_hour < 15
    weekend = row["Dato"].weekday() >= 5

    # ASSISTENT RATES
    if helligdag:
        return 230 if dag else 240

    if weekend:
        return 230 if dag else 240

    return 220 if dag else 225

# --------------------------------------------------
# INVOICE GENERATION
# --------------------------------------------------
def generer_faktura(df, fakturanr, helligdage):
    inv = df.copy()

    inv["Helligdag"] = inv["Dato"].isin(helligdage).map({True:"Ja", False:"Nej"})
    inv = inv.rename(columns={"Tid":"Tidsperiode","Personalegruppe":"Personale"})

    # ---------- PERSONALE NORMALIZATION (BULLETPROOF) ----------
    inv["Personale"] = (
        inv["Personale"]
        .astype(str)
        .str.replace("\u00A0"," ", regex=False)
        .str.replace(r"\s+"," ", regex=True)
        .str.strip()
        .str.lower()
    )

    # Map assistant 2 → assistant
    inv.loc[inv["Personale"] == "assistent 2", "Personale"] = "assistent"

    # ---------- RATE ----------
    inv["Takst"] = inv.apply(beregn_takst, axis=1)

    # ---------- KIRSTEN +10 ----------
    inv.loc[
        inv["Jobfunktion_raw"]
        .astype(str)
        .str.contains(r"\bkirsten\b", case=False, na=False),
        "Takst"
    ] += 10

    inv["Samlet"] = inv["Timer"] * inv["Takst"]

    inv = inv[
        ["Dato","Medarbejder","Tidsperiode","Timer","Personale",
         "Jobfunktion","Helligdag","Takst","Samlet"]
    ]

    uge = inv["Dato"].dt.isocalendar().week.min()

    # --------------------------------------------------
    # EXCEL
    # --------------------------------------------------
    excel = BytesIO()
    inv.to_excel(excel, index=False)
    excel.seek(0)

    # --------------------------------------------------
    # PDF
    # --------------------------------------------------
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    if os.path.exists("logo.png"):
        pdf.image("logo.png", 10, 5, 30)

    pdf.set_xy(140, 10)
    pdf.set_font("Arial","B",18)
    pdf.cell(50,10,f"INVOICE {fakturanr}")

    pdf.ln(30)
    pdf.set_font("Arial","",10)
    pdf.cell(0,6,f"Invoice date: {date.today().strftime('%d.%m.%Y')}", ln=True)
    pdf.ln(5)

    widths = [18,30,24,10,20,22,14,12,18]

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
            str(r["Medarbejder"]),
            r["Tidsperiode"],
            f"{r['Timer']:.1f}",
            r["Personale"],
            r["Jobfunktion"],
            r["Helligdag"],
            str(int(r["Takst"])),
            f"{r['Samlet']:.2f}"
        ]
        for v,w in zip(row, widths):
            pdf.cell(w,8,v,1)
        pdf.ln()
        total += r["Samlet"]

    moms = total * 0.25
    pdf.ln(5)
    pdf.set_font("Arial","B",10)
    pdf.cell(0,6,f"Subtotal: {total:.2f} kr", ln=True)
    pdf.cell(0,6,f"Moms (25%): {moms:.2f} kr", ln=True)
    pdf.cell(0,6,f"Total incl. VAT: {total + moms:.2f} kr", ln=True)

    pdf_bytes = pdf.output(dest="S").encode("latin-1")

    return (
        excel,
        f"FAKTURA_{fakturanr}_UGE_{uge}.xlsx",
        BytesIO(pdf_bytes),
        f"FAKTURA_{fakturanr}_UGE_{uge}.pdf"
    )

# --------------------------------------------------
# UI
# --------------------------------------------------
st.title("MR Rekruttering – Fakturagenerator")

file = st.file_uploader("Upload Excel file", type=["xlsx"])
fakturanr = st.number_input("Invoice number", min_value=1, step=1)

if file and fakturanr:
    raw = pd.read_excel(file)
    clean = rens_data(raw)

    dates = sorted(clean["Dato"].dt.date.unique())
    helligdage = [pd.Timestamp(d) for d in st.multiselect("Select holidays", dates)]

    if st.button("Generate invoice"):
        xls, xls_name, pdf, pdf_name = generer_faktura(clean, fakturanr, helligdage)
        st.success("Invoice generated successfully")
        st.download_button("Download Excel", xls, file_name=xls_name)
        st.download_button("Download PDF", pdf, file_name=pdf_name)

