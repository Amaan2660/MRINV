import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import date
from fpdf import FPDF
import os

st.set_page_config(page_title="MR Fakturagenerator", layout="centered")

# -------------------- STYLING --------------------
st.markdown("""
<style>
body { background-color:#aa1e1e; }
[data-testid="stAppViewContainer"] > .main {
    background-color:white;
    border-radius:10px;
    padding:2rem;
    max-width:900px;
    margin:auto;
}
</style>
""", unsafe_allow_html=True)

st.image("logo.png", width=80)

# -------------------- DATA RENS --------------------
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

    byer = ["allerød","egedal","frederiksund","solrød","herlev","ringsted"]

    def find_by(txt):
        t = str(txt).lower()
        for b in byer:
            if b in t:
                return b
        return "andet"

    df["Jobfunktion"] = df["Jobfunktion"].apply(find_by)
    return df.sort_values(["Jobfunktion","Dato","Starttid"])

# -------------------- TAKST --------------------
def beregn_takst(row):
    personale = row["Personale"]
    helligdag = row["Helligdag"] == "Ja"

    start_hour = int(row["Tidsperiode"].split("-")[0][:2])
    dag = start_hour < 15
    weekend = row["Dato"].weekday() >= 5

    if personale != "assistent":
        return 0  # hård beskyttelse

    if helligdag:
        return 230 if dag else 240

    if weekend:
        return 230 if dag else 240

    return 220 if dag else 225

# -------------------- FAKTURA --------------------
def generer_faktura(df, fakturanr, helligdage):
    inv = df.copy()
    inv["Helligdag"] = inv["Dato"].isin(helligdage).map({True:"Ja", False:"Nej"})
    inv = inv.rename(columns={"Tid":"Tidsperiode","Personalegruppe":"Personale"})

    # --------- KRITISK NORMALISERING (KAN IKKE FEJLE) ---------
    inv["Personale"] = (
        inv["Personale"]
        .astype(str)
        .str.replace("\u00A0"," ", regex=False)
        .str.replace(r"\s+"," ", regex=True)
        .str.strip()
        .str.lower()
    )

    # Accepter kun Assistent / Assistent 2
    inv.loc[inv["Personale"].str.contains(r"\bassistent\b"), "Personale"] = "assistent"

    # --------- TAKST ---------
    inv["Takst"] = inv.apply(beregn_takst, axis=1)

    # --------- KIRSTEN +10 ---------
    inv.loc[
        inv["Jobfunktion_raw"].astype(str)
        .str.contains(r"\bkirsten\b", case=False, na=False),
        "Takst"
    ] += 10

    inv["Samlet"] = inv["Timer"] * inv["Takst"]

    inv = inv[
        ["Dato","Medarbejder","Tidsperiode","Timer","Personale",
         "Jobfunktion","Helligdag","Takst","Samlet"]
    ]

    uge = inv["Dato"].dt.isocalendar().week.min()

    # -------------------- EXCEL --------------------
    xls = BytesIO()
    inv.to_excel(xls, index=False)
    xls.seek(0)

    # -------------------- PDF --------------------
    # -------------------- PDF --------------------
pdf = FPDF()
pdf.add_page()
pdf.set_auto_page_break(auto=True, margin=15)

if os.path.exists("logo.png"):
    pdf.image("logo.png", 10, 5, 30)

pdf.set_xy(140, 10)
pdf.set_font("Arial", "B", 18)
pdf.cell(50, 10, f"INVOICE {fakturanr}")

pdf.ln(30)
pdf.set_font("Arial", "", 10)
pdf.cell(0, 6, f"Fakturadato: {date.today().strftime('%d.%m.%Y')}", ln=True)
pdf.ln(4)

# ✅ PASSENDE KOLONNEBREDDER (SUM = 180 mm)
widths = [18, 30, 24, 10, 20, 22, 14, 12, 18]

# ---------- HEADER ----------
pdf.set_font("Arial", "B", 9)
pdf.set_x(10)
for h, w in zip(inv.columns, widths):
    pdf.cell(w, 8, h, border=1)
pdf.ln()

# ---------- ROWS ----------
pdf.set_font("Arial", "", 9)
total = 0

for _, r in inv.iterrows():
    pdf.set_x(10)
    values = [
        r["Dato"].strftime("%d.%m.%Y"),
        str(r["Medarbejder"]),
        str(r["Tidsperiode"]),
        f"{r['Timer']:.1f}",
        str(r["Personale"]),
        str(r["Jobfunktion"]),
        str(r["Helligdag"]),
        f"{int(r['Takst'])}",
        f"{r['Samlet']:.2f}",
    ]

    for v, w in zip(values, widths):
        pdf.cell(w, 8, v, border=1)
    pdf.ln()

    total += r["Samlet"]

# ---------- TOTALER ----------
moms = total * 0.25
pdf.ln(5)
pdf.set_font("Arial", "B", 10)
pdf.cell(0, 6, f"Subtotal: {total:.2f} kr", ln=True)
pdf.cell(0, 6, f"Moms (25%): {moms:.2f} kr", ln=True)
pdf.cell(0, 6, f"Total inkl. moms: {total + moms:.2f} kr", ln=True)

pdf_bytes = pdf.output(dest="S").encode("latin-1")


# -------------------- UI --------------------
st.title("MR Rekruttering – Fakturagenerator")

file = st.file_uploader("Upload Excel", type=["xlsx"])
nr = st.number_input("Fakturanummer", min_value=1, step=1)

if file and nr:
    raw = pd.read_excel(file)
    clean = rens_data(raw)

    dates = sorted(clean["Dato"].dt.date.unique())
    holidays = [pd.Timestamp(d) for d in st.multiselect("Vælg helligdage", dates)]

    if st.button("Generer faktura"):
        xls,xls_name,pdf,pdf_name = generer_faktura(clean,nr,holidays)
        st.success("Faktura genereret")
        st.download_button("Download Excel",xls,file_name=xls_name)
        st.download_button("Download PDF",pdf,file_name=pdf_name)
