import streamlit as st
import json
import io
import base64
from PIL import Image
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from openai import OpenAI
from html import escape
import tempfile
from fpdf import FPDF
import os  # yukarıya ekle (zaten varsa tekrar ekleme)
from PIL import Image, ImageDraw, ImageFont
import tempfile
import textwrap

st.set_page_config(layout="wide")
st.title("📚 Exam Coach Uygulaması")

# --- Stil ---
st.markdown("""
    <style>
    .scroll-box {
        max-height: 600px;
        overflow-y: scroll;
        padding: 1rem;
        border: 1px solid #ccc;
        border-radius: 0.5rem;
        background-color: #f9f9f9;
    }
    .gpt-box {
        background-color: #1c1c1c;
        padding: 1.5rem;
        margin-top: 1rem;
        border-radius: 10px;
        color: white;
        font-family: 'Courier New', monospace;
    }
    </style>
""", unsafe_allow_html=True)

# --- Oturum güvenliği ---
if "app_initialized" not in st.session_state:
    st.session_state.clear()
    st.session_state.app_initialized = True

if "service_info" not in st.session_state:
    st.session_state.service_info = {}

for key in ["selected_question", "selected_answer", "show_question", "show_answer", "gpt_response", "gpt_cost"]:
    if key not in st.session_state:
        st.session_state[key] = None if "selected" in key else False

# --- JSON Yükleme ---
with st.expander("📂 JSON Anahtarını Yükle", expanded=True):
    uploaded_json = st.file_uploader("Google Servis Hesabı JSON'unu yükleyin", type=["json","txt"])
    if uploaded_json:
        try:
            json_content = json.load(uploaded_json)
            st.session_state.service_info = {
                "project_id": json_content.get("project_id", ""),
                "private_key_id": json_content.get("private_key_id", ""),
                "private_key": json_content.get("private_key", "").replace("\\n", "\n"),
                "client_email": json_content.get("client_email", ""),
                "client_id": json_content.get("client_id", ""),
                "openai_api_key": json_content.get("OPEN_AI_KEY", ""),
                "dersler": json_content.get("dersler", {})
            }
            st.session_state.openai_client = OpenAI(api_key=st.session_state.service_info["openai_api_key"])
            st.success("JSON ve API Key yüklendi ✅")
        except Exception as e:
            st.error(f"Yükleme hatası: {e}")

# --- Google Drive'dan Dosya Çekme ---
def load_drive_files(folder_id, key):
    try:
        credentials_dict = {
            "type": "service_account",
            "project_id": st.session_state.service_info["project_id"],
            "private_key_id": st.session_state.service_info["private_key_id"],
            "private_key": st.session_state.service_info["private_key"],
            "client_email": st.session_state.service_info["client_email"],
            "client_id": st.session_state.service_info["client_id"],
            "token_uri": "https://oauth2.googleapis.com/token"
        }
        credentials = service_account.Credentials.from_service_account_info(
            credentials_dict,
            scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )
        service = build("drive", "v3", credentials=credentials)
        st.session_state[key + "_service"] = service
        results = service.files().list(
            q=f"'{folder_id}' in parents and mimeType='image/png' and trashed=false",
            fields="files(id, name)"
        ).execute()
        st.session_state[key + "_files"] = results.get("files", [])
        st.success(f"{key} klasöründen {len(results.get('files', []))} dosya bulundu ✅")
    except Exception as e:
        st.error(f"{key} klasörü yüklenemedi: {e}")

# --- Yardımcı Fonksiyonlar ---
def download_file(service, file_id):
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)
        return fh
    except Exception as e:
        st.error(f"Görsel indirilemedi: {e}")
        return None

def show_image(fh, caption):
    try:
        st.image(Image.open(fh), caption=caption, use_container_width=True)
    except:
        st.error("Görsel gösterilemedi.")

def image_to_base64_raw(fh):
    fh.seek(0)
    return base64.b64encode(fh.read()).decode("utf-8")

# --- Soru Seçimi ---
with st.expander("📑 Soru Seçimi ve Gösterimi", expanded=True):
    dersler_dict = st.session_state.service_info.get("dersler", {})
    secili_ders = st.selectbox("📘 Ders Seçin", list(dersler_dict.keys()), key="ders_selector")

    if secili_ders:
        soru_folder_id = dersler_dict[secili_ders]["SORU"]
        cevap_folder_id = dersler_dict[secili_ders]["CEVAP"]

        if "yuklenen_ders" not in st.session_state or st.session_state.yuklenen_ders != secili_ders:
            load_drive_files(soru_folder_id, "SORU")
            load_drive_files(cevap_folder_id, "CEVAP")
            st.session_state.yuklenen_ders = secili_ders

        soru_listesi = [f["name"] for f in st.session_state.get("SORU_files", [])]

        with st.form("soru_secimi_form"):
            selected_question = st.selectbox("🔢 Bir soru seçin", soru_listesi, key="soru_selector") if soru_listesi else None
            show_q_button = st.form_submit_button("🖼️ Göster")

        if show_q_button and selected_question:
            st.session_state.selected_question = selected_question
            st.session_state.show_question = True

        if st.session_state.show_question and st.session_state.selected_question:
            st.markdown("#### 📝 Seçilen Soru")
            st.markdown('<div class="scroll-box">', unsafe_allow_html=True)
            for f in st.session_state.get("SORU_files", []):
                if f["name"] == st.session_state.selected_question:
                    fh = download_file(st.session_state.SORU_service, f["id"])
                    st.session_state.question_fh = fh
                    show_image(fh, f["name"])
            st.markdown('</div>', unsafe_allow_html=True)

# --- Cevap Seçimi ---
with st.expander("✅ Cevap Seçimi ve Gösterimi", expanded=True):
    cevap_listesi = [f["name"] for f in st.session_state.get("CEVAP_files", [])]
    with st.form("cevap_secimi_form"):
        selected_answer = st.selectbox("Bir cevap seçin", cevap_listesi, key="cevap_selector") if cevap_listesi else None
        show_a_button = st.form_submit_button("🖼️ Göster")
    if show_a_button and selected_answer:
        st.session_state.selected_answer = selected_answer
        st.session_state.show_answer = True
    if st.session_state.show_answer and st.session_state.selected_answer:
        st.markdown("#### ✅ Seçilen Cevap")
        st.markdown('<div class="scroll-box">', unsafe_allow_html=True)
        for f in st.session_state.get("CEVAP_files", []):
            if f["name"] == st.session_state.selected_answer:
                fh = download_file(st.session_state.CEVAP_service, f["id"])
                st.session_state.answer_fh = fh
                show_image(fh, f["name"])
        st.markdown('</div>', unsafe_allow_html=True)





def create_combined_image_with_header(question_fh, answer_fh=None, course_name="Ders"):

    header_text = (
        "Below, you will find an actuarial exam question and its corresponding answer (if provided).\n"
        "You are expected to solve the question using a professional actuarial approach.\n"
        "This is an actuarial exam question, and your explanation should reflect that level of understanding.\n\n"
        "The question and the answer are in Turkish.\n"
        "You must also explain your answer in Turkish.\n"
        "Clearly explain each step of your solution.\n\n"
        "In addition to solving the question, you are also expected to discuss relevant background topics or concepts that support the solution."
    )

    # Font
    try:
        font = ImageFont.truetype("arial.ttf", size=18)
        label_font = ImageFont.truetype("arialbd.ttf", size=24)
    except:
        font = ImageFont.load_default()
        label_font = ImageFont.load_default()

    # Üst yazıyı sar ve header görüntüsü oluştur
    wrapped_text = textwrap.fill(header_text, width=100)
    lines = wrapped_text.split('\n')
    line_height = font.getbbox("A")[3] - font.getbbox("A")[1]
    padding = 20
    header_height = line_height * len(lines) + 2 * padding

    # Görselleri yükle
    question_fh.seek(0)
    q_img = Image.open(question_fh).convert("RGB")
    q_img = add_overlay_label(q_img, "🟦 Question Part", label_font)

    if answer_fh:
        answer_fh.seek(0)
        a_img = Image.open(answer_fh).convert("RGB")
        a_img = add_overlay_label(a_img, "🟩 Answer Part", label_font)
    else:
        a_img = None

    # Genişlik ayarla
    img_width = max(q_img.width, a_img.width if a_img else 0)
    header_img = Image.new("RGB", (img_width, header_height), color=(255, 255, 255))
    draw = ImageDraw.Draw(header_img)
    y = padding
    for line in lines:
        draw.text((padding, y), line, font=font, fill=(0, 0, 0))
        y += line_height

    # Birleştir
    total_height = header_img.height + q_img.height + (a_img.height if a_img else 0)
    combined_img = Image.new("RGB", (img_width, total_height), color=(255, 255, 255))
    y_offset = 0
    combined_img.paste(header_img, (0, y_offset))
    y_offset += header_img.height
    combined_img.paste(q_img, (0, y_offset))
    y_offset += q_img.height
    if a_img:
        combined_img.paste(a_img, (0, y_offset))

    # Geçici olarak kaydet
    temp_path = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
    combined_img.save(temp_path, format="PNG")
    return temp_path

# 🔧 Yardımcı fonksiyon: Görselin üstüne etiket ekle
def add_overlay_label(img, label_text, font):
    overlay = img.copy()
    draw = ImageDraw.Draw(overlay)
    text_width = draw.textlength(label_text, font=font)
    box_height = font.getbbox("A")[3] - font.getbbox("A")[1] + 20
    draw.rectangle([(0, 0), (img.width, box_height)], fill=(230, 230, 230))
    draw.text(((img.width - text_width) // 2, 10), label_text, font=font, fill=(0, 0, 0))
    return overlay




if st.button("📄 GPT için görsel oluştur ve indir"):
    if st.session_state.get("question_fh"):
        selected_course = st.session_state.get("ders_selector", "Ders").replace(" ", "_")
        selected_question = st.session_state.get("selected_question", "Soru").replace(" ", "_")

        out_path = create_combined_image_with_header(
            question_fh=st.session_state["question_fh"],
            answer_fh=st.session_state.get("answer_fh"),
            course_name=selected_course
        )

        file_name = f"{selected_course}_{selected_question}"
        if not file_name.lower().endswith(".png"):
            file_name += ".png"

        with open(out_path, "rb") as f:
            st.download_button(
                "⬇️ Görseli indir",
                data=f.read(),  # Tüm içeriği belleğe alıyoruz
                file_name=file_name,
                mime="image/png"
            )

        # ✅ Dosyayı indir düğmesinden sonra sil
        try:
            os.remove(out_path)
        except Exception as e:
            st.warning(f"Geçici dosya silinemedi: {e}")
    else:
        st.warning("Lütfen önce bir soru görseli seçin.")
