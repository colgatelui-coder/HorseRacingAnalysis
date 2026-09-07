import io
import sqlite3
from flask import Flask, render_template, request
import pandas as pd
from HorseRacingAnalysis import app
from flask import redirect, url_for, flash
import requests
import re
from bs4 import BeautifulSoup  # 如果沒有安裝，請在終端機輸入 pip install beautifulsoup4
from flask import render_template, redirect, url_for
import datetime

DB_FILE = "racing.db"

def init_db():
    """初始化 SQL 資料庫"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS racing_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            馬名 TEXT, 完整馬匹編號 TEXT, 當前年齡 INTEGER, 季度場次 INTEGER,
            名次 TEXT, 日期 TEXT, 馬場_跑道 TEXT, 途程_米 INTEGER,
            場地狀況 TEXT, 賽事班次 TEXT, 檔位 INTEGER, 騎師 TEXT, 練馬師 TEXT, 評分 INTEGER, 獨贏賠率 REAL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS injury_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            烙印編號 TEXT, 馬名 TEXT, 傷患日期 TEXT, 詳情 TEXT, 通过日期 TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def save_races_to_sql(csv_text):
    """處理賽績 CSV 上傳 (大容錯版)"""
    try:
        if not csv_text.strip():
            return "上傳失敗：檔案內容為空！"
            
        # 💡 關鍵升級：sep=None + engine='python' 自動判定是逗號還是 Tab 鍵分隔
        df = pd.read_csv(io.StringIO(csv_text.strip()), sep=None, engine='python')
        
        # 清除欄位名稱前後的空白字元
        df.columns = df.columns.str.strip()
        
        # 自動更換可能出現的變體欄位名
        rename_dict = {'馬場/跑道': '馬場_跑道', '途程(米)': '途程_米', '途程': '途程_米'}
        df = df.rename(columns=rename_dict)

        # 檢查欄位
        required = ['馬名', '名次', '評分', '途程_米', '季度場次', '日期']
        missing = [col for col in required if col not in df.columns]
        if missing:
            return f"上傳失敗：您的檔案缺少必要欄位 {missing}。目前檔案內現有的欄位為：{list(df.columns)}"
        
        # 清洗數據，防止文字造成 SQL 報錯
        df['馬名'] = df['馬名'].astype(str).str.strip()
        
        conn = sqlite3.connect(DB_FILE)
        df.to_sql('racing_records', conn, if_exists='append', index=False)
        conn.commit()
        conn.close()
        return "SUCCESS: 🎉 賽績檔案已成功匯入 SQL 數據庫！"
    except Exception as e:
        return f"錯誤：解析賽績檔案時發生崩潰，原因為: {str(e)}"

def save_injuries_to_sql(csv_text):
    """處理傷患紀錄 CSV 上傳 (大容錯版)"""
    try:
        if not csv_text.strip():
            return "上傳失敗：傷患檔案內容為空！"
            
        df = pd.read_csv(io.StringIO(csv_text.strip()), sep=None, engine='python')
        df.columns = df.columns.str.strip()
        
        if '日期' in df.columns and '傷患日期' not in df.columns:
            df = df.rename(columns={'日期': '傷患日期'})
            
        required = ['馬名', '詳情']
        missing = [col for col in required if col not in df.columns]
        if missing:
            return f"上傳失敗：傷患檔案缺少必要欄位 {missing}。目前有的欄位為：{list(df.columns)}"

        df = df.dropna(subset=['詳情'])
        df['馬名'] = df['馬名'].fillna("未知馬匹").astype(str).str.strip()

        conn = sqlite3.connect(DB_FILE)
        df.to_sql('injury_records', conn, if_exists='append', index=False)
        conn.commit()
        conn.close()
        return "SUCCESS: 🩸 傷患紀錄報告已成功保存至 SQL 資料庫！"
    except Exception as e:
        return f"錯誤：解析傷患檔案時發生崩潰，原因為: {str(e)}"

def load_and_analyze_from_sql():
    """AI 分析主引擎：以可加載基石代碼重塑之全新四階漏斗防線對齊版"""
    conn = sqlite3.connect(DB_FILE)
    try:
        df = pd.read_sql_query("SELECT * FROM racing_records", conn)
        df_injuries = pd.read_sql_query("SELECT * FROM injury_records", conn)
        conn.close()
        
        if df.empty: return [], None

        def clean_place(x):
            try: return int(str(x).strip())
            except: return None

        df['名次_數字'] = df['名次'].apply(clean_place)
        df['評分_數字'] = pd.to_numeric(df['評分'], errors='coerce')
        
        # 💡 安全對齊：確保途程(米)與途程_米百分之百能順暢相容讀取
        if '途程(米)' in df.columns:
            df['途程_米'] = pd.to_numeric(df['途程(米)'], errors='coerce')
        else:
            df['途程_米'] = pd.to_numeric(df.get('途程_米', 1200), errors='coerce')
            
        if '當前年齡' in df.columns:
            df['當前年齡_num'] = pd.to_numeric(df['當前年齡'], errors='coerce')
        else:
            df['當前年齡_num'] = pd.to_numeric(df.get('年齡', 5), errors='coerce')

        # 兩位數年份安全解碼
        df['r_dt'] = pd.to_datetime(df['日期'], format='%d/%m/%y', errors='coerce', dayfirst=True)
        backup_dt = pd.to_datetime(df['日期'], format='%d/%m/%Y', errors='coerce', dayfirst=True)
        df['r_dt'] = df['r_dt'].fillna(backup_dt)

        top_3_df = df[df['名次_數字'] <= 3].dropna(subset=['評分_數字'])
        results = []
        unique_horses = df['馬名'].unique()

        real_injury_keywords = ['心律', '流血', '不良於行', '受傷', '手術', 
                               '肌腱', '筋腱', '懸韌帶', '韌帶', '骨', 
                               '關節', '碎骨', '呼吸道', '喘鳴症', '流鼻血']
        exclusion_keywords = ['表現欠佳', '令人失望', '難以接受', '八歲或以上', 
                              '食慾不振', '發燒', '閹割', '煩躁', '被卡住']
        black_trainers = ["丁冠豪", "大衛希斯", "葉楚航", "鄭俊偉", "徐雨石"]

        for horse in unique_horses:
            horse_all = df[df['馬名'] == horse].copy()
            
            # 💡 基石代碼之高智慧雙重實質時間降序排序 (最新在最前)
            try:
                horse_all['temp_idx'] = pd.to_numeric(horse_all['季度場次'], errors='coerce').fillna(0)
                horse_all = horse_all.sort_values(by=['r_dt', 'temp_idx'], ascending=[False, False])
            except:
                horse_all = horse_all.sort_values(by='r_dt', ascending=False)

            if horse_all.empty: continue
            
            # 💡 聽話修正：100% 沿用您最安全的原生 iloc[0] 提取語法，絕不報錯
            latest_row = horse_all.iloc[0]
            if pd.isna(latest_row['評分_數字']): continue
            latest_rating = int(latest_row['評分_數字'])
            
            try: horse_age_int = int(latest_row['當前年齡_num'])
            except: horse_age_int = 5
            
            trainer_clean = str(latest_row['練馬師']).strip() if latest_row['練馬師'] else "未知"

            # 精確擷取最頂部最新的 3 場歷史數據
            recent_3 = horse_all.head(3)
            has_top3_recently = any(p <= 3 for p in recent_3['名次_數字'].tolist() if p is not None)

            # -------------------------------------------------
            # 🗄️ 全新四階新版本狀態初始化與推算 (完美融合)
            # -------------------------------------------------
            v2_health = "🟢 健康無礙"
            v2_ability = "常規參賽馬"
            v2_new_horse = "查有歷史數據"
            v2_other_status = "常規戰力狀態"

            latest_top3_dt = None
            latest_injury_dt = None
            is_new_horse_real = True
            has_top3_last_season = False
            min_rate, max_rate = 0, 0
            gold_range_str = "暫無上名評分"

            horse_top3 = top_3_df[top_3_df['馬名'] == horse]
            
            if not horse_top3.empty:
                is_new_horse_real = False
                v2_new_horse = "🟢 查有賽績"
                min_rate = int(horse_top3['評分_數字'].min())
                max_rate = int(horse_top3['評分_數字'].max())
                gold_range_str = f"{min_rate} - {max_rate} 分"
                
                top3_races = horse_all[horse_all['名次_數字'] <= 3]
                if not top3_races.empty:
                    latest_top3_dt = top3_races['r_dt'].max()

                # 利用純日期精確推算 25/26 馬季（上季）實績
                cond_25 = (horse_all['r_dt'].dt.year == 2025) & (horse_all['r_dt'].dt.month >= 9)
                cond_26 = (horse_all['r_dt'].dt.year == 2026) & (horse_all['r_dt'].dt.month <= 7)
                last_season_races = horse_all[cond_25 | cond_26]
                
                if not last_season_races.empty:
                    last_season_top3 = last_season_races[last_season_races['名次_數字'] <= 3]
                    if not last_season_top3.empty:
                        has_top3_last_season = True

            # 💡 【全新防線 1：健康狀況判定與上名平反機制】
            if not df_injuries.empty and '馬名' in df_injuries.columns:
                horse_injuries = df_injuries[df_injuries['馬名'] == horse].copy()
                if not horse_injuries.empty:
                    horse_injuries['dt'] = pd.to_datetime(
                        horse_injuries['傷患日期'], errors='coerce', dayfirst=True
                    )
                    for _, inj_row in horse_injuries.iterrows():
                        detail_text = str(inj_row.get('詳情', ''))
                        if any(kw in detail_text for kw in real_injury_keywords) \
                           and not any(ekw in detail_text for ekw in exclusion_keywords):
                            
                            if pd.notna(inj_row['dt']):
                                if latest_injury_dt is None or inj_row['dt'] > latest_injury_dt:
                                    latest_injury_dt = inj_row['dt']

            if latest_injury_dt is not None:
                if latest_top3_dt is not None and latest_top3_dt > latest_injury_dt:
                    v2_health = "🟢 健康無礙"
                else:
                    v2_health = "🚨 嚴重生理傷患馬"

            # 💡 【全新防線 2：沒能力馬 / 退化期判定】
            if not is_new_horse_real and not has_top3_last_season:
                if horse_age_int >= 6: v2_ability = "🚫 退化期老馬"
                else: v2_ability = "🚫 沒有能力馬"

            # 💡 【全新防線 3：插班 / 新馬馬房判定】
            if is_new_horse_real:
                if trainer_clean in black_trainers: v2_new_horse = "🚫 未操完馬房"
                else: v2_new_horse = "🆕 新馬/插班馬"

            # 💡 【全新防線 4：其他上季曾上名馬 5分有利水位阻力比對】
            if not is_new_horse_real and has_top3_last_season:
                if horse_age_int <= 5:
                    v2_other_status = "🌱 成長期"
                else:
                    if latest_rating > 0 and max_rate > 0:
                        if abs(latest_rating - max_rate) <= 5:
                            v2_other_status = "📈 平穩向上"
                        else:
                            v2_other_status = "📉 飽和調整期"

            # 🛠️ 🎯 【工程師 Debug 控制台】：完全聽話輸出 3 場歷史名次
            if horse in ["快活英雄"]:
                print("\n" + "⚙️  "*12 + f"【 {horse} ．近 3 場名次追蹤日誌 】" + " ⚙️ "*12)
                idx = 1
                for _, r_race in recent_3.iterrows():
                    print(f"  🏁 [最新第 {idx} 場] ➔ 日期: {r_race['日期']} | 場次: {r_race['季度場次']} | 名次: {r_race['名次']} | 評分: {r_race['評分']} | 練馬師: {r_race['練馬師']}")
                    idx += 1
                print(f"  📊 數據分析判定結果 ➔ 歷史最高上名評分: {max_rate} 分 | 近3場是否有前三名: {has_top3_recently}")
                print("="*90 + "\n")

            # -------------------------------------------------
            # 🛡️ 智慧判定轉換為主頁狀態與預警燈號 (漏斗排除)
            # -------------------------------------------------
            if "🚨" in v2_health:
                status, badge_color = "💥 傷患排除", "danger"
                desc = "❌ 排除防線(一)：查出該駒患有未復原之嚴重生理歷史傷患。"
            elif "🚫" in v2_ability:
                status, badge_color = f"💥 {v2_ability}", "danger"
                desc = f"❌ 排除防線(二)：上季出賽完全無上名，狀態已大幅退化。"
            elif "🚫" in v2_new_horse:
                status, badge_color = "💥 未操完馬房", "danger"
                desc = f"❌ 排除防線(三)：新馬/插班馬，且落在冷門黑名單馬房【{trainer_clean}】。"
            elif max_rate > 0 and latest_rating > (max_rate + 2) and v2_other_status not in ["🌱 成長期", "📈 平穩向上"]:
                status, badge_color = "❌ 評分過高", "danger"
                desc = f"❌ 排除防線(四)：當前({latest_rating}分)超出最高勝出天花板，阻力過大。"
            else:
                if "📈" in v2_other_status:
                    status, badge_color = "🟢 平穩向上", "success"
                    desc = f"✨ 阻力有利：現時評分與歷史勝出頂峰在 5分 水位內，火氣仍盛。"
                elif "🌱" in v2_other_status:
                    status, badge_color = "🌱 成長期", "success"
                    desc = f"✨ 進步神速：({horse_age_int}歲)年輕上季有上名主力主力駒，空間大。"
                else:
                    status, badge_color = "⚠️ 進入射程", "warning"
                    desc = f"當前評分 ({latest_rating}分) 落在黃金區間，列入防守留底觀察。"

            if "🚫" in v2_ability: label_text = v2_ability
            elif "🚫" in v2_new_horse: label_text = "❌ 未操完馬房"
            elif "🚨" in v2_health: label_text = "🩹 嚴重傷患"
            else: label_text = v2_other_status

            results.append({
                'name': horse, 'age': horse_age_int, 'total': len(horse_all), 'top3': len(horse_top3),
                'range': gold_range_str,
                'dist': f"{int(horse_all['途程_米'].value_counts().idxmax()) if not horse_all['途程_米'].dropna().empty else 1200}米",
                'current': latest_rating, 'status': status, 'color': badge_color, 'desc': desc,
                'potential': label_text, 'potential_color': "success" if "🟢" in status or "🌱" in status or "📈" in status else "danger" if "💥" in status or "❌" in status else "warning",
                'potential_desc': desc, 'injury': "🚨 有傷患紀錄" if "🚨" in v2_health else "🟢 健康無礙",
                'injury_alert': True if "🚨" in v2_health else False, 'injury_text': ""
            })
        return results, None
    except Exception as e:
        if conn: conn.close()
        return [], f"分析失敗: {str(e)}"


@app.route('/', methods=['GET', 'POST'])
@app.route('/home', methods=['GET', 'POST'])
def home():
    error_msg, success_msg = None, None
    if request.method == 'POST':
        if 'race_file' in request.files:
            file = request.files['race_file']
            if file.filename != '':
                stream = io.StringIO(file.stream.read().decode("utf-8-sig", errors="ignore"))
                res = save_races_to_sql(stream.read())
                if res.startswith("SUCCESS"): success_msg = res.replace("SUCCESS: ", "")
                else: error_msg = res
        elif 'injury_file' in request.files:
            file = request.files['injury_file']
            if file.filename != '':
                stream = io.StringIO(file.stream.read().decode("utf-8-sig", errors="ignore"))
                res = save_injuries_to_sql(stream.read())
                if res.startswith("SUCCESS"): success_msg = res.replace("SUCCESS: ", "")
                else: error_msg = res
    data_results, err = load_and_analyze_from_sql()
    if err: error_msg = err
    return render_template('index.html', data=data_results, error_msg=error_msg, success_msg=success_msg)
@app.route('/reset_database', methods=['POST'])
def reset_database():
    """🚨 安全清空機制：一鍵清空 SQL 資料庫後自動重定向回首頁，防止 404"""
    global CURRENT_RACING_DATA
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # 清空兩張資料表與計數器
        cursor.execute("DELETE FROM racing_records")
        cursor.execute("DELETE FROM injury_records")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='racing_records'")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='injury_records'")
        
        conn.commit()
        conn.close()
        
        CURRENT_RACING_DATA = ""
        # 💡 使用 Flask 內建的 flash 機制，把成功訊息帶回首頁
        return redirect(url_for('home'))
        
    except Exception as e:
        if conn: conn.close()
        return f"清空失敗: {str(e)}"


@app.route('/hkjc_live', methods=['GET', 'POST'])
def hkjc_live():
    """1. 接收來自主頁人手輸入的參數，並轉發至排位分頁"""
    if request.method == 'POST':
        # 接收主頁輸入的日期與場地
        input_date = request.form.get('race_date')   # 格式如: "2026-09-06"
        input_venue = request.form.get('race_venue') # "ST" 或 "HV"
        
        if input_date:
            # 將標準日期的橫線 "-" 換成馬會官網網址接受的斜線 "/"
            formatted_date = input_date.replace('-', '/')
            # 預設導向該人手指定賽期的第 1 場
            return redirect(url_for('view_race', race_date_str=formatted_date.replace('/', '-'), venue_code=input_venue, race_no=1))
            
    # 如果是直接點擊連結，給予預設值開鑼日
    return redirect(url_for('view_race', race_date_str="2026-09-06", venue_code="ST", race_no=1))
    
@app.route('/hkjc_live/<race_date_str>/<venue_code>/<int:race_no>')
def view_race(race_date_str, venue_code, race_no):
    """🌐 萬能排位解碼引擎：全能打包抬頭與雙推介列至 JSON 快取完全體"""
    import json, os
    t_dt = race_date_str.replace('-', '/')
    cache_file = "hkjc_cache.json"
    race_horses, dan_nums_sorted, not_adv_sorted = [], [], []
    found_race_nos = list(range(1, 10))
    race_details = {'title': f"第 {race_no} 場 賽事排位", 'datetime': f"{t_dt} 指定賽期", 'track': f"{venue_code} 馬場", 'class_prize': "數據加載中..."}

    use_cache = False
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f: cache_data = json.load(f)
            if cache_data.get('race_date') == race_date_str and cache_data.get('venue') == venue_code:
                found_race_nos = cache_data.get('found_race_nos', found_race_nos)
                if str(race_no) in cache_data.get('races_data', {}):
                    c_race = cache_data['races_data'][str(race_no)]
                    race_horses = c_race['race_horses']
                    # 🚀 🎯 智慧快取命中：直接從 JSON 裡完美取出上次存好的雙列推介與抬頭資料！
                    dan_nums_sorted = c_race.get('dan_nums', [])
                    not_adv_sorted = c_race.get('not_adv_dan_nums', [])
                    race_details = c_race.get('race_details', race_details)
                    use_cache = True
                    print(f"⚡ [全包快取命中] 賽事資料與雙列推介已成功由 JSON 秒開派發！")
        except: pass

    if not use_cache:
        print(f"🐢 [快取未命中] 正在發動 SQL 精準過濾兼全包打包大作戰...")
        hdrs = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        try:
            init_resp = requests.get(f"https://racing.hkjc.com/zh-hk/local/information/racecard?racedate={t_dt}&Racecourse={venue_code}&RaceNo=1", headers=hdrs, timeout=10)
            if init_resp.status_code == 200:
                init_resp.encoding = 'utf-8'
                temp_races = [int(re.search(r'RaceNo=(\d+)', a['href'], re.I).group(1)) for a in BeautifulSoup(init_resp.text, 'html.parser').find_all('a', href=True) if 'RaceNo=' in a['href'] and re.search(r'RaceNo=(\d+)', a['href'], re.I)]
                if temp_races: found_race_nos = sorted(list(set([r for r in temp_races if r <= 12])))

            all_today_horse_names = set()
            parsed_races_html = {}
            
            for r_idx in found_race_nos:
                loop_resp = requests.get(f"https://racing.hkjc.com/zh-hk/local/information/racecard?racedate={t_dt}&Racecourse={venue_code}&RaceNo={r_idx}", headers=hdrs, timeout=10)
                if loop_resp.status_code != 200: continue
                loop_resp.encoding = 'utf-8'
                l_soup = BeautifulSoup(loop_resp.text, 'html.parser')
                parsed_races_html[r_idx] = l_soup
                
                table = l_soup.find('table', id='racecardlist') or l_soup.find('table', class_='table_bd')
                if table and table.find('tr'):
                    for row in table.find_all('tr'):
                        if row.find('th') or any(k in str(row.get('class', '')) for k in ['header', 'hidden']): continue
                        cols = row.find_all('td')
                        if len(cols) >= 4:
                            raw_n = " ".join(cols[3].text.split()).strip() if len(cols) > 3 else ""
                            nm_m = re.search(r'([\u4e00-\u9fa5]+)', raw_n)
                            if nm_m: all_today_horse_names.add(nm_m.group(1).strip())

            db_rec, db_inj = pd.DataFrame(), pd.DataFrame()
            if all_today_horse_names:
                conn = sqlite3.connect(DB_FILE)
                placeholders = ', '.join('?' for _ in all_today_horse_names)
                name_list = list(all_today_horse_names)
                db_rec = pd.read_sql_query(f"SELECT * FROM racing_records WHERE 馬名 IN ({placeholders})", conn, params=name_list)
                db_inj = pd.read_sql_query(f"SELECT * FROM injury_records WHERE 馬名 IN ({placeholders})", conn, params=name_list)
                conn.close()

            new_cache = {'race_date': race_date_str, 'venue': venue_code, 'found_race_nos': found_race_nos, 'races_data': {}}

            for r_idx in found_race_nos:
                if r_idx not in parsed_races_html: continue
                l_soup = parsed_races_html[r_idx]
                l_pure = "".join(l_soup.text.split())

                l_details = {'title': f"第 {r_idx} 場 賽事排位", 'datetime': f"{t_dt} 指定賽期", 'track': f"{'沙田' if venue_code=='ST' else '跑馬地'}馬場", 'class_prize': "常規賽事"}
                t_m = re.search(r'(草地,.*?\d+米|草地.*?賽道\d+米|\d+米)', " ".join(l_soup.text.split()))
                if t_m: l_details['track'] = t_m.group(1).strip()
                c_m = re.search(r'(第[\u4e00-\u9fa5一二三四五六]班)', l_pure)
                if c_m:
                    p_m = re.search(r'(獎金:\$\d+,\d+,\d+|獎金:\$\d+,\d+)', l_pure)
                    l_details['class_prize'] = f"{p_m.group(1) + ' | ' if p_m else ''}{c_m.group(1)}"
                if re.search(r'(第\d+場-[\u4e00-\u9fa5]+讓賽)', l_pure): l_details['title'] = re.search(r'(第\d+場-[\u4e00-\u9fa5]+讓賽)', l_pure).group(1)

                l_horses, l_dan, l_not_adv = [], [], []
                table = l_soup.find('table', id='racecardlist') or l_soup.find('table', class_='table_bd')
                if table and table.find('tr'):
                    rows = table.find_all('tr')
                    idx = {'num': 0, 'hist': 1, 'name': 3, 'wt': 5, 'jky': 6, 'drw': 7, 'trn': 8, 'rtg': 9}
                    th_l = [th.text.strip() for th in (table.find('tr', class_='table_header') or table.find('tr')).find_all(['th', 'td'])]
                    for i, txt in enumerate(th_l):
                        if '馬匹編號' in txt or '馬號' in txt: idx['num'] = i
                        elif '近績' in txt: idx['hist'] = i
                        elif '馬名' in txt: idx['name'] = i
                        elif '負磅' in txt: idx['wt'] = i
                        elif '騎師' in txt: idx['jky'] = i
                        elif '檔位' in txt: idx['drw'] = i
                        elif '練馬師' in txt: idx['trn'] = i
                        elif '評分' in txt: idx['rtg'] = i

                    for row in rows:
                        if row.find('th') or any(k in str(row.get('class', '')) for k in ['header', 'hidden']): continue
                        cols = row.find_all('td')
                        if len(cols) >= 10:
                            try:
                                num = re.search(r'\d+', cols[idx['num']].text.strip()).group(0)
                                raw_n = " ".join(cols[idx['name']].text.split()).strip()
                                nm_m = re.search(r'([\u4e00-\u9fa5]+)\s*\(([A-Z0-9]+)\)', raw_n)
                                p_name = nm_m.group(1).strip() if nm_m else raw_n.strip()
                                j_cln = " ".join(cols[idx['jky']].text.split()).strip().replace('\n', '')
                                if "綵衣" in raw_n or "負磅" in j_cln: continue

                                drw = "".join(filter(str.isdigit, cols[idx['drw']].text.strip()))
                                if not drw and idx['drw'] + 1 < len(cols): drw = "".join(filter(str.isdigit, cols[idx['drw'] + 1].text.strip()))
                                t_cln = "".join(re.findall(r'[\u4e00-\u9fa5]+', cols[idx['trn'] + 1 if idx['trn'] + 1 < len(cols) else idx['trn']].text.strip())).replace("檔", "")
                                
                                rtg_d, cell_idx = "-", 0
                                for cell in cols:
                                    if cell_idx > idx['trn']:
                                        if cell.text.strip().isdigit() and int(cell.text.strip()) != int(num) and cell.text.strip() != drw:
                                            rtg_d = cell.text.strip()
                                            break
                                    cell_idx += 1
                                if rtg_d == "-" and (idx['rtg'] + 1) < len(cols) and re.search(r'\d+', cols[idx['rtg'] + 1].text.strip()): rtg_d = re.search(r'\d+', cols[idx['rtg'] + 1].text.strip()).group(0)

                                curr_rate = int(rtg_d) if rtg_d.isdigit() else 0
                                is_ex, rsn_txt, min_r, max_r, is_not_adv = calc_funnel(p_name, curr_rate, t_cln, db_rec, db_inj)

                                if not is_ex:
                                    l_dan.append(str(num))
                                    if is_not_adv: l_not_adv.append(str(num))

                                l_horses.append({
                                    'num': num, 'history': " ".join(cols[idx['hist']].text.split()).strip(), 'name': f"{nm_m.group(1)} [{nm_m.group(2)}]" if nm_m else raw_n,
                                    'weight': "".join(filter(str.isdigit, cols[idx['wt']].text.strip())) + " 磅", 'jockey': j_cln, 'draw': drw + " 檔" if drw else "-",
                                    'trainer': t_cln, 'rating': rtg_d if rtg_d != "-" else "", 'is_excluded': is_ex, 'exclusion_reason': "✨ 通過推介" if not (is_ex or is_not_adv) else rsn_txt, 'gold_range': f"{min_r}-{max_r}分" if max_r > 0 else "🆕新馬/插班馬"
                                })
                            except: continue

                # 💡 核心打包點：把每一場的「推介、不建議列與賽事資料」一網打盡通通寫入 JSON！
                new_cache['races_data'][str(r_idx)] = {
                    'race_horses': l_horses, 
                    'dan_nums': sorted(list(set(l_dan)), key=int), 
                    'not_adv_dan_nums': sorted(list(set(l_not_adv)), key=int), 
                    'race_details': l_details
                }
                print(f"✅ 已下載全包打包 ➔ 第 {r_idx} 場")

            with open(cache_file, 'w', encoding='utf-8') as f: json.dump(new_cache, f, ensure_ascii=False, indent=4)
            if str(race_no) in new_cache['races_data']:
                c_race = new_cache['races_data'][str(race_no)]
                race_horses, dan_nums_sorted, not_adv_sorted, race_details = c_race['race_horses'], c_race['dan_nums'], c_race['not_adv_dan_nums'], c_race['race_details']
        except Exception as e: race_details['title'] = f"⚠️ 連線失敗: {str(e)}"



    return render_template('hkjc_live.html', race_horses=race_horses, current_race=race_no, race_details=race_details,
                           race_date_str=race_date_str, venue_code=venue_code, dan_nums_json=dan_nums_sorted, not_adv_json=not_adv_sorted, races=found_race_nos)

def calc_funnel(name, rate, trn, db_r, db_i):
    """🧠 核心大腦：完全對齊天花板「硬排除」與評分過低「不建議馬膽」之漏斗分流版"""
    ex, rsn, min_r, max_r = False, "", 0, 0
    bt = ["丁冠豪", "大衛希斯", "葉楚航", "鄭俊偉", "徐雨石"]
    ik = ['心律', '流血', '不良於行', '受傷', '手術', '肌腱', '筋腱', '懸韌帶', '韌帶', '骨', '關節', '碎骨', '呼吸道', '喘鳴症', '流鼻血']
    ek = ['表現欠佳', '令人失望', '難以接受', '八歲或以上', '食慾不振', '發燒', '閹割', '煩躁', '被卡住']
    v2_h, v2_a, v2_n, v2_o, age, l_t3, l_inj, is_new, has_t3 = "🟢健康", "常規", "有賽績", "常規", 5, None, None, True, False

    try: curr_rate_int = int(rate)
    except: curr_rate_int = 0

    search_name = str(name).strip()

    if not db_r.empty:
        h = db_r[db_r['馬名'] == search_name].copy()
        if not h.empty:
            is_new = False
            h['名_num'] = h['名次'].apply(lambda x: int(str(x).strip()) if str(x).strip().isdigit() else 99)
            h['dt'] = pd.to_datetime(h['日期'], errors='coerce', dayfirst=True).fillna(pd.to_datetime(h['日期'], format='%d/%m/%Y', errors='coerce', dayfirst=True))
            try: h = h.sort_values(by=['dt', '季度場次'], ascending=[False, False])
            except: h = h.sort_values(by='dt', ascending=False)
            try: age = int(float(str(h.iloc[0].get('當前年齡', 5))))
            except: age = 5
            t3 = h[h['名_num'] <= 3]
            if not t3.empty:
                min_r = int(pd.to_numeric(t3['評分'], errors='coerce').min())
                max_r = int(pd.to_numeric(t3['評分'], errors='coerce').max())
                l_t3 = t3['dt'].max()
            c25, c26 = (h['dt'].dt.year == 2025) & (h['dt'].dt.month >= 9), (h['dt'].dt.year == 2026) & (h['dt'].dt.month <= 7)
            if not h[c25 | c26].empty and not h[c25 | c26][h['名_num'] <= 3].empty: has_t3 = True

    if is_new and not db_i.empty and not db_i[db_i['馬名'] == search_name].empty: is_new = False
    if not db_i.empty:
        j = db_i[db_i['馬名'] == search_name].copy()
        if not j.empty:
            j['dt'] = pd.to_datetime(j['傷患日期'], errors='coerce', dayfirst=True)
            for _, r in j.iterrows():
                if any(k in str(r['詳情']) for k in ik) and not any(e in str(r['詳情']) for e in ek):
                    if pd.notna(r['dt']) and (l_inj is None or r['dt'] > l_inj): l_inj = r['dt']

    if l_inj is not None: v2_h = "🟢健康" if (l_t3 is not None and l_t3 > l_inj) else "🚨嚴重傷患"
    if not is_new and not has_t3: v2_a = "🚫 退化期老馬" if age >= 6 else "🚫 沒有能力馬"
    if is_new: v2_n = "🚫 未操完馬房" if trn in bt else "🆕新馬"
    if not is_new and has_t3:
        if age <= 5: v2_o = "🌱成長期"
        else:
            if curr_rate_int > 0 and max_r > 0: v2_o = "📈平穩向上" if abs(curr_rate_int - max_r) <= 5 else "📉飽和調整期"

    if "🚨" in v2_h: return True, "❌ 排除(防線一)：生理傷患。", min_r, max_r, False
    if "🚫" in v2_a: return True, f"❌ 排除(防線二)：{v2_a}。", min_r, max_r, False
    if "🚫" in v2_n: return True, f"❌ 排除(防線三)：馬房未操完。", min_r, max_r, False

    is_not_adv = False
    if curr_rate_int > max_r and max_r > 0:
        if v2_o in ["📉飽和調整期", "常規"] or (curr_rate_int > max_r + 2 and v2_o not in ["🌱成長期", "📈平穩向上"]):
            return True, f"❌ 排除(防線四)：當前評分({curr_rate_int}分)超出最高勝出天花板({max_r}分)阻力過大。", min_r, max_r, False

    if min_r > 0 and curr_rate_int < min_r and v2_o not in ["🌱成長期"]:
        is_not_adv = True
        rsn = f"⚠️ 不建議馬膽：低於黃金下限({min_r}分)。"

    return ex, rsn if is_not_adv else "", min_r, max_r, is_not_adv



