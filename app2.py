import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import hashlib
from datetime import datetime, timedelta
from supabase import create_client, Client

# ==================== Supabase 配置 ====================
# ⚠️ 请替换为你的 Supabase 项目信息
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "https://vlkotlfcsuwubrtkaixy.supabase.co")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZsa290bGZjc3V3dWJydGthaXh5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTk0MTIxOTcsImV4cCI6MjA3NDk4ODE5N30.8YClf-Rc2kcxo2lZIWGGIKmB5vJtfTGQcHO6hkls6Xw")

# 初始化 Supabase 客户端
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"❌ Supabase 连接失败: {e}")
    st.stop()

# ==================== 用户管理系统 ====================

def hash_password(password):
    """密码加密"""
    return hashlib.md5(password.encode()).hexdigest()

def register_user(username, password, expiry_days=365):
    """注册新用户"""
    try:
        # 检查用户名是否存在
        result = supabase.table("users").select("username").eq("username", username).execute()
        if result.data:
            return False, "用户名已存在"
        
        expiry_date = (datetime.now() + timedelta(days=expiry_days)).strftime("%Y-%m-%d")
        
        # 插入新用户
        data = {
            "username": username,
            "password": hash_password(password),
            "role": "user",
            "expiry_date": expiry_date,
            "created_date": datetime.now().strftime("%Y-%m-%d")
        }
        
        supabase.table("users").insert(data).execute()
        return True, f"注册成功！账号有效期至 {expiry_date}"
    
    except Exception as e:
        return False, f"注册失败: {str(e)}"

def login(username, password):
    """用户登录验证"""
    try:
        # 查询用户
        result = supabase.table("users").select("*").eq("username", username).execute()
        
        if not result.data:
            return False, "用户名不存在"
        
        user = result.data[0]
        
        # 验证密码
        if user["password"] != hash_password(password):
            return False, "密码错误"
        
        # 检查账号是否过期
        expiry_date = datetime.strptime(user["expiry_date"], "%Y-%m-%d")
        if datetime.now() > expiry_date:
            return False, f"账号已过期（过期日期：{user['expiry_date']}）"
        
        return True, user
    
    except Exception as e:
        return False, f"登录失败: {str(e)}"

def get_all_users():
    """获取所有用户（管理员功能）"""
    try:
        result = supabase.table("users").select("*").execute()
        return result.data
    except Exception as e:
        st.error(f"获取用户列表失败: {e}")
        return []

def update_user_expiry(username, new_expiry_date):
    """更新用户过期日期（管理员功能）"""
    try:
        supabase.table("users").update({"expiry_date": new_expiry_date}).eq("username", username).execute()
        return True
    except Exception as e:
        st.error(f"更新失败: {e}")
        return False

def delete_user(username):
    """删除用户（管理员功能）"""
    try:
        if username == "admin":
            return False
        supabase.table("users").delete().eq("username", username).execute()
        return True
    except Exception as e:
        st.error(f"删除失败: {e}")
        return False

# ==================== GSW_Bergkamen 数据处理逻辑 ====================

def process_md_pipes(related, kommentar):
    """处理MD管道并返回LV条目"""
    lv_entries = []
    rohr_menge = 0

    for _, related_row in related.iterrows():
        verbund_str = str(related_row.get("Verbund", ""))

        if "MD12" in verbund_str:
            match = re.search(r'(\d+)MD12', verbund_str)
            if match:
                count = int(match.group(1))
                lv_entries.append(f"{count} x 1.3.1.1.01 - (Leerrohrverband 12x10/6)")
                rohr_menge += count
            else:
                lv_entries.append(f"1 x 1.3.1.1.01 - (Leerrohrverband 12x10/6)")
                rohr_menge += 1

        if "MD7" in verbund_str:
            match = re.search(r'(\d+)MD7', verbund_str)
            if match:
                count = int(match.group(1))
                lv_entries.append(f"{count} x 1.3.1.1.03 - (Leerrohrverband 7x16/12)")
                rohr_menge += count
            else:
                lv_entries.append(f"1 x 1.3.1.1.03 - (Leerrohrverband 7x16/12)")
                rohr_menge += 1

    if rohr_menge > 1:
        zusaetzliche_rohre = rohr_menge - 1
        lv_entries.append(f"{zusaetzliche_rohre} x 1.1.1.1.11 - (Verlegung eines zusätzlichen Rohrverbundes)")
        if "Handschachtung" in kommentar:
            lv_entries.append("1 x N1.4.0 - (Handschachtung)")

    return lv_entries

def process_hausanschluss(related):
    """处理Hausanschlussrohr并返回LV条目"""
    hausanschluss_code = "Hausanschlussrohr 10/6"
    hausanschluss_pos = "1.3.1.1.04"
    hausanschluss_count = sum(hausanschluss_code in str(v) for v in related["Verbund"])

    if hausanschluss_count > 0:
        return [f"{hausanschluss_count} x {hausanschluss_pos} - ({hausanschluss_code})"]
    return []

def process_special_cases(kommentar, mapping):
    """处理特殊情况（无长度的情况）"""
    if kommentar in mapping:
        return [mapping[kommentar]]
    return []

def process_surface_excavation(kommentar, laenge, breite, related):
    """处理表面开挖工作"""
    lv_entries = []

    lv_entries.append(f"Länge : {laenge} m")
    lv_entries.append(f"{round(laenge / 100, 2)} x 1.1.1.1.02 - (Verkehrsregelung und Verkehrssicherung)")

    oberfl_mapping = {
        "Pflaster": "1.1.1.1.08",
        "Asphalt": "1.1.1.1.07",
        "Wassergebundene Decke": "1.1.1.1.09",
        "Fahrbahn": "1.1.1.1.06"
    }

    key = kommentar.split("+")[0].strip()
    lv_entries.append(f"1 x {oberfl_mapping[key]} - (Leitungsgraben, Oberfläche: {key})")

    if breite and key in ["Pflaster", "Asphalt", "Fahrbahn"]:
        mehrbreite = 0
        if key == "Fahrbahn" and breite > 0.4:
            mehrbreite = breite - 0.4
            code = "1.4.1.1.01"
            beschr = "10 cm Mehrgrabenbreite: Asphalt"
        elif key == "Pflaster" and breite > 0.6:
            mehrbreite = breite - 0.6
            code = "1.4.1.1.02"
            beschr = "10 cm Mehrgrabenbreite: Pflaster"
        elif key == "Asphalt" and breite > 0.6:
            mehrbreite = breite - 0.6
            code = "1.4.1.1.01"
            beschr = "10 cm Mehrgrabenbreite: Asphalt"

        if mehrbreite > 0:
            e = round(mehrbreite * 10)
            lv_entries.append(f"{e} x {code} - ({beschr})")

    md_entries = process_md_pipes(related, kommentar)
    lv_entries.extend(md_entries)

    hausanschluss_entries = process_hausanschluss(related)
    lv_entries.extend(hausanschluss_entries)

    return lv_entries

def process_pressung(kommentar, laenge, related):
    """处理压力安装工作"""
    lv_entries = []

    lv_entries.append(f"Länge : {laenge} m")
    lv_entries.append(f"{round(laenge / 100, 2)} x 1.1.1.1.02 - (Verkehrsregelung und Verkehrssicherung)")

    lv_entries.append(f"{len(related)} x N1.1.0 - (Pressung 63mm Druchmesser)")

    md_entries = process_md_pipes(related, kommentar)
    lv_entries.extend(md_entries)

    hausanschluss_entries = process_hausanschluss(related)
    lv_entries.extend(hausanschluss_entries)

    if kommentar == "Pressung":
        lv_entries.append("2 x N1.2.0 - (Herstellung Start- und Zielgrube)")
        lv_entries.append("2 x N1.3.1 - (Mehraufwand unter Pflasteroberflächen)")

    return lv_entries

def process_einziehen(related):
    """处理拉入工作"""
    lv_entries = []

    lv_entries.append(f"{len(related)} x 1.1.1.1.10 - (Rohrverbund einziehen)")

    md_entries = process_md_pipes(related, "")
    lv_entries.extend(md_entries)

    hausanschluss_entries = process_hausanschluss(related)
    lv_entries.extend(hausanschluss_entries)

    return lv_entries

def get_related_rows(df, id_prefix):
    """获取相关行"""
    return df[df["ID"].astype(str).str.strip().apply(lambda x: x == id_prefix or x.startswith(f"{id_prefix}_"))]

def parse_length(laenge_raw):
    """解析长度字段"""
    try:
        return float(laenge_raw) if laenge_raw and str(laenge_raw).lower() != "null" else None
    except (ValueError, TypeError):
        return None

def parse_width(breite_raw):
    """解析宽度字段"""
    if not breite_raw:
        return None
    try:
        return float(str(breite_raw).strip().replace(",", "."))
    except (ValueError, TypeError):
        return None

def process_single_row(row, df):
    """处理单行数据"""
    id_val = str(row.get("ID", "")).strip()
    if "_" in id_val or not id_val.isdigit():
        return ""

    id_prefix = id_val
    laenge_raw = str(row.get("Länge (m)", "")).strip()
    kommentar = str(row.get("Kommentar", "")).strip()
    bezeichner = str(row.get("Bezeichner", "")).strip()
    breite_raw = str(row.get("Breite (m)", "")).strip()

    laenge = parse_length(laenge_raw)
    breite = parse_width(breite_raw)

    lv = [f"Pos {id_val}:"]

    if laenge is None:
        mapping = {
            "Suchschachtung": "1 x 1.1.1.1.14 - Suchschachtung",
            "Multifunktionsgehäuse": "1 x 1.1.1.1.13 - Multifunktionsgehäuse setzen",
            "Kabelschacht": "1 x 1.1.1.1.12 - Kabelschacht setzen"
        }
        special_entries = process_special_cases(kommentar, mapping)
        lv.extend(special_entries)
    else:
        lv.append(bezeichner)
        related = get_related_rows(df, id_prefix)

        if kommentar.split("+")[0].strip() in ["Pflaster", "Asphalt", "Wassergebundene Decke", "Fahrbahn"]:
            surface_entries = process_surface_excavation(kommentar, laenge, breite, related)
            lv.extend(surface_entries)
        elif kommentar.startswith("Pressung"):
            pressung_entries = process_pressung(kommentar, laenge, related)
            lv.extend(pressung_entries)
        elif kommentar == "Einziehen":
            einziehen_entries = process_einziehen(related)
            lv.extend(einziehen_entries)

    return "\n".join(lv)

CODES_WITH_WIDTH_DEPTH = {
    "1.1.1.1.06",
    "1.1.1.1.07",
    "1.1.1.1.08",
    "1.1.1.1.09",
}

def line_contains_width(code):
    return code in CODES_WITH_WIDTH_DEPTH

def line_contains_depth(code):
    return code in CODES_WITH_WIDTH_DEPTH

pattern = re.compile(r"([\d.,]+)\s*[x×]\s*([A-Za-z0-9.]+)")

def unpack_val(val):
    """将任何输入统一转换为数值或None"""
    s = str(val).strip()
    if not s or s.upper() == "NULL" or s.lower() == "none":
        return None
    try:
        return float(s.replace(",", "."))
    except (ValueError, TypeError):
        return None

def extract_num(p):
    """从位置字符串中提取数字"""
    m = re.search(r"(\d+)", p)
    return int(m.group(1)) if m else 0

def extract_ta_from_layer(layer_str):
    """从Layer字段中提取TA编号"""
    if not layer_str or pd.isna(layer_str):
        return ""
    
    layer_str = str(layer_str)
    match = re.search(r'(TA\d+)', layer_str)
    if match:
        return match.group(1)
    return layer_str

def process_gsw_bergkamen(df):
    """GSW_Bergkamen项目的完整处理流程"""
    if "LV" not in df.columns:
        df["LV"] = ""
    
    for idx, row in df.iterrows():
        df.at[idx, "LV"] = process_single_row(row, df)
    
    rows = []
    
    for idx, feat in df.iterrows():
        lv = feat.get("LV")
        if not lv or pd.isna(lv):
            continue
        
        pos = lv.splitlines()[0].replace(":", "").replace(" ", "")
        ta = extract_ta_from_layer(feat.get("Layer"))
        bz = feat.get("Bezeichner")
        
        laenge = unpack_val(feat.get("Länge (m)"))
        breite = unpack_val(feat.get("Breite (m)"))
        tiefe = unpack_val(feat.get("Tiefe (m)"))
        
        for line in lv.splitlines():
            m = pattern.search(line)
            if not m:
                continue
            menge_raw, code = m.groups()
            menge = unpack_val(menge_raw)
            
            rows.append({
                "Pos": pos,
                "TA": ta,
                "Bezeichner": bz,
                "LV-Code": code,
                "Länge": laenge if laenge is not None else np.nan,
                "Breite": (breite if breite is not None and line_contains_width(code) else np.nan),
                "Tiefe": (tiefe if tiefe is not None and line_contains_depth(code) else np.nan),
                "Faktor": menge if menge is not None else np.nan
            })
    
    df_output = pd.DataFrame(rows, columns=[
        "Pos", "TA", "Bezeichner", "LV-Code", "Länge", "Breite", "Tiefe", "Faktor"
    ])
    
    df_output["PosNum"] = df_output["Pos"].apply(extract_num)
    df_output = df_output.sort_values(by=["PosNum"], kind="mergesort").drop(columns=["PosNum"])
    
    return df_output

def process_projekt_a(df):
    """Projekt A 的处理逻辑"""
    df["Projekt"] = "Projekt A"
    return df

def process_projekt_b(df):
    """Projekt B 的处理逻辑"""
    df["Projekt"] = "Projekt B"
    return df

# ==================== Streamlit 应用界面 ====================

st.set_page_config(page_title="数据处理系统", page_icon="📊", layout="wide")

# Session State 初始化
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "current_user" not in st.session_state:
    st.session_state.current_user = None
if "user_role" not in st.session_state:
    st.session_state.user_role = None

# 创建标签页
if st.session_state.logged_in:
    if st.session_state.user_role == "admin":
        tabs = st.tabs(["📂 Datenverarbeitung", "👥 Benutzerverwaltung", "🚪 Abmelden"])
    else:
        tabs = st.tabs(["📂 Datenverarbeitung", "🚪 Abmelden"])
else:
    tabs = st.tabs(["🔑 Anmeldung", "📝 Registrierung"])

# ==================== 未登录状态 ====================
if not st.session_state.logged_in:
    # 登录标签
    with tabs[0]:
        st.header("🔑 Benutzeranmeldung")
        col1, col2 = st.columns([1, 1])
        
        with col1:
            login_username = st.text_input("👤 Benutzername", key="login_user")
            login_password = st.text_input("🔒 Passwort", type="password", key="login_pass")
            
            if st.button("Einloggen", key="login_btn", use_container_width=True):
                with st.spinner("登录中..."):
                    success, result = login(login_username, login_password)
                    if success:
                        st.session_state.logged_in = True
                        st.session_state.current_user = login_username
                        st.session_state.user_role = result["role"]
                        st.success(f"✅ Willkommen, {login_username}!")
                        st.rerun()
                    else:
                        st.error(f"❌ {result}")
        
        with col2:
            st.info("""
            **测试账号**：
            - 管理员：admin / admin123
            - 或者在右侧注册新账号
            
            💡 数据存储在 Supabase 云端
            """)
    
    # 注册标签
    with tabs[1]:
        st.header("📝 Neuen Benutzer registrieren")
        col1, col2 = st.columns([1, 1])
        
        with col1:
            reg_username = st.text_input("👤 Benutzername wählen", key="reg_user")
            reg_password = st.text_input("🔒 Passwort wählen", type="password", key="reg_pass")
            reg_password_confirm = st.text_input("🔒 Passwort bestätigen", type="password", key="reg_pass_conf")
            
            if st.button("Registrieren", key="register_btn", use_container_width=True):
                if not reg_username or not reg_password:
                    st.error("❌ Bitte alle Felder ausfüllen")
                elif reg_password != reg_password_confirm:
                    st.error("❌ Passwörter stimmen nicht überein")
                elif len(reg_password) < 6:
                    st.error("❌ Passwort muss mindestens 6 Zeichen lang sein")
                else:
                    with st.spinner("注册中..."):
                        success, message = register_user(reg_username, reg_password, expiry_days=365)
                        if success:
                            st.success(f"✅ {message}")
                            st.info("Sie können sich jetzt im Tab 'Anmeldung' einloggen")
                        else:
                            st.error(f"❌ {message}")
        
        with col2:
            st.info("""
            **注册说明**：
            - 新账号默认有效期为1年
            - 密码至少6个字符
            - 数据永久保存在云端
            """)

# ==================== 已登录状态 ====================
else:
    # 数据处理标签
    with tabs[0]:
        st.header("📂 Excel-Datenverarbeitung")
        
        # 显示用户信息
        users = get_all_users()
        current_user_info = next((u for u in users if u["username"] == st.session_state.current_user), {})
        expiry_date = current_user_info.get("expiry_date", "未知")
        
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            st.info(f"👤 当前用户: **{st.session_state.current_user}**")
        with col2:
            st.info(f"📅 账号有效期至: **{expiry_date}**")
        with col3:
            if st.session_state.user_role == "admin":
                st.success("👑 管理员")
            else:
                st.success("👤 普通用户")
        
        st.divider()
        
        # 文件处理
        hochgeladene_datei = st.file_uploader("📤 Excel-Datei hochladen", type=["xlsx", "xls"])
        projekt = st.selectbox("📌 Projekt auswählen", ["Projekt A", "Projekt B", "GSW_Bergkamen"])
        
        if hochgeladene_datei:
            df = pd.read_excel(hochgeladene_datei)
            st.write("📊 Vorschau der Datei:")
            st.dataframe(df.head())
            
            if st.button("➡️ Ausgabe erzeugen", use_container_width=True):
                with st.spinner("⏳ Verarbeitung läuft..."):
                    try:
                        if projekt == "GSW_Bergkamen":
                            verarbeitetes_df = process_gsw_bergkamen(df)
                        elif projekt == "Projekt A":
                            verarbeitetes_df = process_projekt_a(df)
                        elif projekt == "Projekt B":
                            verarbeitetes_df = process_projekt_b(df)
                        
                        st.success("✅ Verarbeitung abgeschlossen!")
                        st.write("📊 Vorschau der Ergebnisse:")
                        st.dataframe(verarbeitetes_df.head(20))
                        
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                            verarbeitetes_df.to_excel(writer, index=False, sheet_name="Abrechnung")
                            
                            if projekt == "GSW_Bergkamen":
                                wb = writer.book
                                ws = writer.sheets["Abrechnung"]
                                num_fmt = wb.add_format({'num_format': '0.00'})
                                ws.set_column('E:H', None, num_fmt)
                        
                        output.seek(0)
                        
                        st.download_button(
                            label="⬇️ Ergebnisdatei herunterladen",
                            data=output,
                            file_name=f"{projekt}_ergebnis.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )
                    
                    except Exception as e:
                        st.error(f"❌ Fehler bei der Verarbeitung: {str(e)}")
                        st.exception(e)
    
    # 管理员用户管理标签
    if st.session_state.user_role == "admin":
        with tabs[1]:
            st.header("👥 Benutzerverwaltung")
            
            users = get_all_users()
            
            # 显示所有用户
            user_data = []
            for user in users:
                user_data.append({
                    "用户名": user["username"],
                    "角色": "管理员" if user["role"] == "admin" else "普通用户",
                    "创建日期": user["created_date"],
                    "过期日期": user["expiry_date"],
                    "状态": "正常" if datetime.now() <= datetime.strptime(user["expiry_date"], "%Y-%m-%d") else "已过期"
                })
            
            df_users = pd.DataFrame(user_data)
            st.dataframe(df_users, use_container_width=True)
            
            st.divider()
            
            # 管理功能
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("🔄 更新用户有效期")
                user_list = [u["username"] for u in users if u["username"] != "admin"]
                if user_list:
                    update_username = st.selectbox("选择用户", user_list, key="update_user")
                    new_expiry = st.date_input("新的过期日期", key="new_expiry")
                    
                    if st.button("更新有效期", use_container_width=True):
                        if update_user_expiry(update_username, new_expiry.strftime("%Y-%m-%d")):
                            st.success(f"✅ 已更新 {update_username} 的有效期至 {new_expiry}")
                            st.rerun()
                        else:
                            st.error("❌ 更新失败")
                else:
                    st.info("暂无可管理的用户")
            
            with col2:
                st.subheader("🗑️ 删除用户")
                user_list_delete = [u["username"] for u in users if u["username"] != "admin"]
                if user_list_delete:
                    delete_username = st.selectbox("选择用户", user_list_delete, key="delete_user")
                    
                    if st.button("删除用户", type="secondary", use_container_width=True):
                        if delete_user(delete_username):
                            st.success(f"✅ 已删除用户 {delete_username}")
                            st.rerun()
                        else:
                            st.error("❌ 删除失败")
                else:
                    st.info("暂无可删除的用户")
    
    # 登出标签
    logout_tab_index = 1 if st.session_state.user_role != "admin" else 2
    with tabs[logout_tab_index]:
        st.header("🚪 Abmelden")
        st.write(f"当前登录用户: **{st.session_state.current_user}**")
        
        if st.button("确认登出", type="primary", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.current_user = None
            st.session_state.user_role = None
            st.success("✅ 已成功登出")
            st.rerun()