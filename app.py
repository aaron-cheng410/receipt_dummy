import streamlit as st
import json
from openai import OpenAI
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
import gspread
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
import tempfile
from PIL import Image
import io
import pillow_heif

hide_streamlit_style = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {visibility: hidden;}
    .viewerBadge_link__1S137 {display: none !important;}
    </style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

hide_streamlit_style = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none;}
    .viewerBadge_link__qRIco {display: none;}
    </style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

client = OpenAI(api_key=st.secrets["openai_api_key"])

creds_dict = st.secrets["gcp_service_account"]

def convert_heic_to_jpeg(uploaded_file):
    uploaded_file.seek(0)
    heif_file = pillow_heif.read_heif(uploaded_file.read())
    image = Image.frombytes(heif_file.mode, heif_file.size, heif_file.data)
    
    jpeg_bytes = io.BytesIO()
    image.save(jpeg_bytes, format="JPEG")
    jpeg_bytes.seek(0)

    # Add required file attributes for OpenAI
    jpeg_bytes.name = uploaded_file.name.replace(".heic", ".jpeg")
    return jpeg_bytes

def upload_file_to_drive(uploaded_file, filename, folder_id=None):
    gauth = GoogleAuth()
    creds_dict = st.secrets["gcp_service_account"]
    scope = ["https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    gauth.credentials = creds
    drive = GoogleDrive(gauth)

    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        tmp_file.write(uploaded_file.getbuffer())
        tmp_path = tmp_file.name

    file_metadata = {'title': filename}
    if folder_id:
        file_metadata['parents'] = [{'id': folder_id}]

    gfile = drive.CreateFile(file_metadata)
    gfile.SetContentFile(tmp_path)
    gfile.Upload(param={'supportsAllDrives': True}) 

    return gfile['id'], gfile['alternateLink']

cost_code_mapping_text = """00 00 00 – Procurement and Contracting Requirements
01 00 00 – General Requirements
02 00 00 – Existing Conditions
03 00 00 – Concrete
04 00 00 – Masonry
05 00 00 – Metals
06 00 00 – Wood, Plastics, and Composites
07 00 00 – Thermal and Moisture Protection
08 00 00 – Openings
09 00 00 – Finishes
10 00 00 – Specialties
11 00 00 – Equipment
12 00 00 – Furnishings
13 00 00 – Special Construction
14 00 00 – Conveying Equipment
21 00 00 – Fire Suppression
22 00 00 – Plumbing
23 00 00 – Heating, Ventilating, and Air Conditioning (HVAC)
25 00 00 – Integrated Automation
26 00 00 – Electrical
27 00 00 – Communications
28 00 00 – Electronic Safety and Security
31 00 00 – Earthwork
32 00 00 – Exterior Improvements
33 00 00 – Utilities
34 00 00 – Transportation
35 00 00 – Waterway and Marine Construction
40 00 00 – Process Interconnections
41 00 00 – Material Processing and Handling Equipment
42 00 00 – Process Heating, Cooling, and Drying Equipment
43 00 00 – Process Gas and Liquid Handling, Purification, and Storage Equipment
44 00 00 – Pollution and Waste Control Equipment
45 00 00 – Industry-Specific Manufacturing Equipment
46 00 00 – Water and Wastewater Equipment
48 00 00 – Electrical Power Generation
50 00 00 – Miscellaneous Expenses"""


st.title('Materials Receipt Submittals')

with st.form("receipt_form"):
    # Dropdown 1
    property = st.selectbox("Select Property", ["", "1245 Willow Creek Drive", "Harbor Point Lofts", "88 Maple Grove Lane", "Oakwood Estates", "3421 Crestview Road", "Silverleaf Court", "Parkside Townhomes", "510 Riverbend Boulevard"])

    
    # Dropdown 2
    st.markdown("#### Payable Party")
    payable_party_dropdown = st.selectbox("Select from list", ["", "Marco Villalobos", "Jacob Miller", "Ethan Brooks", "Tyler Johnson", "Brandon Hayes", "Scott Anderson", "Dylan Carter"], key="dropdown")
    payable_party_manual = st.text_input("Or enter manually:", key="manual_input")
    


    uploaded_files = st.file_uploader("Upload Receipt Image", type=["jpg", "jpeg", "png", "heif", "heic"], accept_multiple_files=True)


    submitted = st.form_submit_button("Submit Form")

    if submitted:
        # Validate all fields
        payable_party = payable_party_manual.strip() if payable_party_manual.strip() else payable_party_dropdown
        if not property or not payable_party or not uploaded_files:
            st.error("Please complete all fields and upload a receipt.")
        else:
            for uploaded_file in uploaded_files:
                with st.spinner("Uploading and processing..."):
                    if uploaded_file is not None and uploaded_file.type in ["image/heic", "image/heif"]:
                        try:
                            uploaded_file = convert_heic_to_jpeg(uploaded_file)
                        except Exception as e:
                            st.error(f"Failed to convert HEIC file: {e}")
                            st.stop()  # Stop execution if conversion fails
                    # Upload file to OpenAI
                    file_id = client.files.create(file=uploaded_file, purpose="vision").id

                    # Build prompt
                    response = client.responses.create(
                        model="gpt-4.1-mini",
                        input=[{
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": (
                                        "From this receipt image, extract:\n"
                                        "- The date of purchase. This is a recent receipt. If the receipt shows a 2-digit year (e.g. '4-2-25'), assume it's 20xx, not 19xx.\n"
                                        "- A list of items with each item's 'name' and 'price'. If there is a small fee for an item, combine the two prices. The fee should not have it's own row. \n"
                                        "- The total tax amount (if present), plus any extra fees, surcharges, or additional subtotal line items not associated with specific items (e.g., environmental fees, cartage, service fees, recycling fees, etc). These should all be treated as part of 'tax'.\n"
                                        "- Assign a cost code to each item based on its name using the mapping below. Do not give any justification. If no matching cost code assign under Miscellaneous Expenses cost code.\n\n"
                                        "Each assigned cost code should be in the format: 'CODE - Description'.\n\n"
                                        "Return a JSON object in this format:\n"
                                        "{\n"
                                        '  "date": "YYYY-MM-DD",\n'
                                        '  "items": [\n'
                                        '    {"name": "Item name", "price": 0.00, "cost_code": "26 00 00 – Electrical"},\n'
                                        '    ...\n'
                                        '  ],\n'
                                        '  "tax": 0.00\n'
                                        "}\n\n"
                                        "Here is the cost code mapping:\n" + cost_code_mapping_text
                                    )
                                },
                                {"type": "input_image", "file_id": file_id},
                            ],
                        }],
                    )

                    drive_file_id, drive_link = upload_file_to_drive(uploaded_file, uploaded_file.name, folder_id="1WoI-aL7zvInQ1whHYjuX4B2V30KOxqDI")

                    raw_text = response.output[0].content[0].text
                    cleaned_text = raw_text.strip('```json').strip('```').strip()
                    parsed = json.loads(cleaned_text)
                    date = parsed["date"]
                    items = parsed["items"]
                    tax = parsed.get("tax", 0.0)

                    df = pd.DataFrame(items)

                    df["price"] = df["price"].astype(float)

                    subtotal = df["price"].sum()

                    df["tax_share"] = df["price"] / subtotal * tax
                    df["amount"] = (df["price"] + df["tax_share"]).round(2)

                    df["Date Invoiced"] = date
                    df['Property'] = property
                    df['Payable Party'] = payable_party
                    df.rename(columns={"name": "Item Name", "cost_code": "Cost Code"}, inplace=True)
            
                    df['Unique ID'] = None
                    df['Worker Name'] = None
                    df['Hours'] = None
                    df['Claim Number'] = None
            
                    df['Invoice Number'] = None
                    df['Project Description'] = df['Item Name']
                    df['Status'] = None
                    df['Form'] = "MATERIALS"
                    df['Drive Link'] = drive_link

                    final_df = df[["Date Invoiced", "Unique ID", "Claim Number", "Worker Name", "Hours", "Item Name", "Property", "amount", 'Payable Party', 'Project Description', "Cost Code", "Form", "Drive Link"]]
                    final_df.rename(columns={"amount": "Amount"}, inplace=True)


                    def upload_to_google_sheet(df):
                        from gspread.utils import rowcol_to_a1

                        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
                        creds_dict = st.secrets["gcp_service_account"]
                        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
                        client = gspread.authorize(creds)

                        sheet = client.open("Materials Submission")
                        worksheet = sheet.worksheet("Submissions")

                        existing = worksheet.get_all_values()

                        # If empty, write headers first
                        if not existing:
                            worksheet.append_row(df.columns.tolist(), value_input_option="USER_ENTERED") 
                            start_row = 2
                        else:
                            start_row = len(existing) + 1

                        # Write all rows in one batch
                        data = df.values.tolist()
                        end_row = start_row + len(data) - 1
                        end_col = len(df.columns)
                        cell_range = f"A{start_row}:{rowcol_to_a1(end_row, end_col)}"

                        worksheet.update(cell_range, data, value_input_option="USER_ENTERED")


        
                    
                    upload_to_google_sheet(final_df)

            st.success('Form Fully Submitted!')
