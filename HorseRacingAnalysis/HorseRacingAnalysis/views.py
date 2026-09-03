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
    """AI 分析引擎：歷史受傷痕跡不消退版！完美識別雙子美麗等曾雙腿不良於行的隱憂馬"""
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
        df['途程_米'] = pd.to_numeric(df['途程_米'], errors='coerce')
        df['季度場次'] = pd.to_numeric(df['季度場次'], errors='coerce')
        df['當前年齡'] = pd.to_numeric(df['當前年齡'], errors='coerce')

        top_3_df = df[df['名次_數字'] <= 3].dropna(subset=['評分_數字'])
        results = []
        unique_horses = df['馬名'].unique()

        # 💡 嚴格的核心生理傷患關鍵字
        real_injury_keywords = ['心律', '流血', '不良於行', '受傷', '手術', '肌腱', '筋腱', '懸韌帶', '韌帶', '骨', '關節', '碎骨', '呼吸道', '喘鳴症', '流鼻血']
        exclusion_keywords = ['表現欠佳', '令人失望', '難以接受', '八歲或以上', '食慾不振', '發燒', '閹割', '煩躁', '被卡住']

        for horse in unique_horses:
            horse_all = df[df['馬名'] == horse].sort_values(by='季度場次', ascending=True)
            horse_top3 = top_3_df[top_3_df['馬名'] == horse]
            
            latest_row = horse_all.iloc[-1]
            if pd.isna(latest_row['評分_數字']): continue
            latest_rating = int(latest_row['評分_數字'])
            horse_age = int(latest_row['當前年齡']) if not pd.isna(latest_row['當前年齡']) else 5

            # 📋 跨表大數據病歷庫精密對比
            horse_injuries = df_injuries[df_injuries['馬名'] == horse]
            has_real_injury = False
            injury_detail = ""

            if not horse_injuries.empty:
                for _, injury_row in horse_injuries.iterrows():
                    detail_text = str(injury_row['詳情'])
                    
                    # 💡 核心升級：只要詳情命中核心生理大傷，不論是否通過消假，一律列入監控！
                    contains_injury = any(kw in detail_text for kw in real_injury_keywords)
                    contains_exclusion = any(kw in detail_text for kw in exclusion_keywords)
                    
                    if contains_injury and not contains_exclusion:
                        has_real_injury = True
                        # 累加所有的傷患詳情，好讓使用者能看到完整的腿傷病史
                        if injury_detail:
                            injury_detail += " | " + detail_text
                        else:
                            injury_detail = detail_text

            if len(horse_top3) == 0:
                min_rate, max_rate = 0, 0
                gold_range_str = "暫無上名評分"
                best_dist = int(horse_all['途程_米'].value_counts().idxmax()) if not horse_all['途程_米'].dropna().empty else 1200
                status, badge_color = "💤 新馬/沉寂中", "dark"
                desc = "此馬於目前上傳的歷史紀錄中尚未有跑入前三名的紀錄，戰力需重新評估。"
                
                # 💡 傷患連動：即使是新馬，只要有受傷歷史，狀態立刻修正！
                if has_real_injury:
                    potential_status, potential_color = "🩹 傷患隱憂 (謹慎觀望)", "dark"
                    potential_desc = f"⚠️ 查出嚴重歷史傷患【{injury_detail}】！雖可能已消假，但骨傷易復發，戰力打折。"
                else:
                    potential_status, potential_color = "💤 觀察中", "secondary"
                    potential_desc = "新馬或尚未開竅，建議先透過即時排位分頁觀察其試閘表現。"
            else:
                min_rate = int(horse_top3['評分_數字'].min())
                max_rate = int(horse_top3['評分_數字'].max())
                gold_range_str = f"{min_rate} - {max_rate} 分"
                best_dist = int(horse_top3['途程_米'].value_counts().idxmax())
                
                recent_3 = horse_all.dropna(subset=['評分_數字', '名次_數字']).tail(3)
                has_rating_near_high = any(r >= (max_rate - 2) for r in recent_3['評分_數字'].tolist())
                has_top3_recently = any(p <= 3 for p in recent_3['名次_數字'].tolist())

                if has_real_injury:
                    potential_status, potential_color = "🩹 傷患隱憂 (謹慎觀望)", "dark"
                    potential_desc = f"⚠️ 歷史獸醫紀錄顯示曾患有【{injury_detail}】！老傷極易復發，建議防守觀望。"
                elif has_rating_near_high and has_top3_recently:
                    if horse_age <= 5:
                        potential_status, potential_color = "🌱 成長中 (戰力再突破)", "success"
                        potential_desc = f"({horse_age}歲) 年輕進步馬！近況大勇且逼近最高評分，上升空間極大。"
                    else:
                        potential_status, potential_color = "📈 平穩向上 (老當益壯)", "info"
                        potential_desc = f"({horse_age}歲) 熟齡火氣仍盛！維持高位評分，體態精壯。"
                else:
                    if horse_age <= 5:
                        potential_status, potential_color = "💤 成長調整中", "warning"
                        potential_desc = "年輕生力軍，目前評分適度回落或近況沉寂，正儲備下次反彈能量。"
                    else:
                        potential_status, potential_color = "📉 評分飽和 / 退化期", "secondary"
                        potential_desc = "高齡馬且近況未能挑戰高位，戰力已呈飽和，宜觀望減分落班。"

                if latest_rating <= (max_rate + 2) and latest_rating >= (min_rate - 2):
                    status, badge_color = "⚠️ 進入射程範圍", "warning"
                    desc = f"當前評分 ({latest_rating}分) 已接近黃金上名區域，隨時會爆冷反彈！"
                elif latest_rating > max_rate:
                    status, badge_color = "❌ 評分過高", "danger"
                    desc = f"當前評分 ({latest_rating}分) 超出過往勝出高位，需等待減分落班。"
                else:
                    status, badge_color = "📉 跌穿底線", "secondary"
                    desc = f"評分已低於過往新低，需留意馬匹是否有退化跡象。"

            results.append({
                'name': horse, 'age': horse_age, 'total': len(horse_all), 'top3': len(horse_top3),
                'range': gold_range_str, 'dist': f"{best_dist}米",
                'current': latest_rating, 'status': status, 'color': badge_color, 'desc': desc,
                'potential': potential_status, 'potential_color': potential_color, 'potential_desc': potential_desc,
                'injury': "🚨 曾受傷患困擾" if has_real_injury else "🟢 健康無礙",
                'injury_alert': has_real_injury, 'injury_text': injury_detail
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
    """🌐 萬能動態排位解碼引擎：第一部分（格式完全對齊空白鍵）"""
    target_date = race_date_str.replace('-', '/')
    url = f"https://racing.hkjc.com/zh-hk/local/information/racecard?racedate={target_date}&Racecourse={venue_code}&RaceNo={race_no}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    race_horses = []
    recommend_numbers = []
    recommend_str = "暫無符合條件之精選馬匹"
    
    race_details = {
        'title': f"第 {race_no} 場 賽事排位", 
        'datetime': f"{target_date} 人手指定賽期",
        'track': f"{'沙田馬場' if venue_code == 'ST' else '跑馬地馬場'} | 草地", 
        'class_prize': "數據加載中..."
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            global_pure_text = "".join(soup.text.split())
            track_match = re.search(r'(草地,.*?\d+米|草地.*?賽道\d+米|\d+米)', " ".join(soup.text.split()))
            if track_match: 
                race_details['track'] = track_match.group(1).strip()
            
            class_match = re.search(r'(第[\u4e00-\u9fa5一二三四五六]班)', global_pure_text)
            if class_match:
                prize_match = re.search(r'(獎金:\$\d+,\d+,\d+|獎金:\$\d+,\d+)', global_pure_text)
                prize_str = prize_match.group(1) + " | " if prize_match else ""
                race_details['class_prize'] = f"{prize_str}{class_match.group(1)}"

            title_match = re.search(r'(第\d+場-[\u4e00-\u9fa5]+讓賽)', global_pure_text)
            if title_match: 
                race_details['title'] = title_match.group(1)

            # 連接本地 SQLite 雙表進行交叉大數據比對
            conn = sqlite3.connect(DB_FILE)
            db_records = pd.read_sql_query("SELECT * FROM racing_records", conn)
            db_injuries = pd.read_sql_query("SELECT * FROM injury_records", conn)
            conn.close()
            # 3. 解析排位表格數據並執行智能篩選
            table = soup.find('table', id='racecardlist') or \
                    soup.find('table', class_='table_bd')
            if table:
                rows = table.find_all('tr')
                idx_map = {'num': 0, 'history': 1, 'name': 3, 'weight': 5, 
                           'jockey': 6, 'draw': 7, 'trainer': 8, 'rating': 9}
                
                header_tr = table.find('tr', class_='table_header') or \
                            table.find('tr')
                if header_tr:
                    th_list = header_tr.find_all(['th', 'td'])
                    for i, th in enumerate(th_list):
                        th_text = th.text.strip()
                        if '馬匹編號' in th_text or '馬號' in th_text: 
                            idx_map['num'] = i
                        elif '近績' in th_text: idx_map['history'] = i
                        elif '馬名' in th_text: idx_map['name'] = i
                        elif '負磅' in th_text: idx_map['weight'] = i
                        elif '騎師' in th_text: idx_map['jockey'] = i
                        elif '檔位' in th_text: idx_map['draw'] = i
                        elif '練馬師' in th_text: idx_map['trainer'] = i
                        elif '評分' in th_text: idx_map['rating'] = i

                real_injury_keywords = ['心律', '流血', '不良於行', '受傷', 
                                       '手術', '肌腱', '筋腱', '懸韌帶', 
                                       '韌帶', '骨', '關節', '碎骨', 
                                       '呼吸道', '喘鳴症', '流鼻血']
                exclusion_keywords = ['表現欠佳', '令人失望', '難以接受', 
                                      '八歲或以上', '食慾不振', '發燒', 
                                      '閹割', '煩躁', '被卡住']
                
                black_trainers = ["丁冠豪", "大衛希斯", "葉楚航", 
                                  "鄭俊偉", "徐雨石"]

                for row in rows:
                    if row.find('th') or \
                       'table_header' in str(row.get('class', '')) or \
                       'hidden' in str(row.get('class', '')):
                        continue
                    
                    cols = row.find_all('td')
                    if len(cols) >= 10:
                        try:
                            num_text = cols[idx_map['num']].text.strip()
                            num_match = re.search(r'\d+', num_text)
                            if not num_match: continue
                            num = num_match.group(0)
                            
                            history = " ".join(cols[idx_map['history']]
                                      .text.split()).strip()
                            raw_name = " ".join(cols[idx_map['name']]
                                       .text.split()).strip()
                            name_match = re.search(
                                r'([\u4e00-\u9fa5]+)\s*\(([A-Z0-9]+)\)', 
                                raw_name
                            )
                            
                            pure_horse_name = name_match.group(1) \
                                              if name_match else raw_name
                            horse_name_display = f"{name_match.group(1)} " \
                                                 f"[{name_match.group(2)}]" \
                                                 if name_match else raw_name

                            weight_digit = "".join(filter(str.isdigit, 
                                           cols[idx_map['weight']]
                                           .text.strip()))
                            jockey_clean = " ".join(cols[idx_map['jockey']]
                                           .text.split()).strip() \
                                           .replace('\n', '')

                            if "綵衣" in horse_name_display or \
                               "負磅" in jockey_clean or \
                               "騎師" in jockey_clean: 
                                continue

                            raw_draw = cols[idx_map['draw']].text.strip()
                            draw_digit = "".join(filter(str.isdigit, 
                                         raw_draw))
                            if not draw_digit and \
                               idx_map['draw'] + 1 < len(cols):
                                draw_digit = "".join(filter(str.isdigit, 
                                             cols[idx_map['draw'] + 1]
                                             .text.strip()))

                            trainer_idx = idx_map['trainer'] + 1 \
                                          if idx_map['trainer'] + 1 < len(cols) \
                                          else idx_map['trainer']
                            raw_trainer = " ".join(cols[trainer_idx]
                                          .text.split()).strip()
                            trainer_clean = "".join(re.findall(
                                            r'[\u4e00-\u9fa5]+', 
                                            raw_trainer.replace('\n', ''))
                                            ).replace("檔", "")

                            rating_digit = "-"
                            for cell in cols:
                                cell_class = str(cell.get('class', '')).lower()
                                if 'rating' in cell_class and \
                                   cell.text.strip().isdigit():
                                    rating_digit = cell.text.strip()
                                    break
                            if rating_digit == "-":
                                for idx_check in range(idx_map['trainer'], 
                                                       len(cols)):
                                    t_val = cols[idx_check].text.strip()
                                    if t_val.isdigit() and t_val != num \
                                       and t_val != draw_digit:
                                        if int(t_val) != 1 or \
                                           idx_check == idx_map['rating'] or \
                                           idx_check == idx_map['rating'] + 1:
                                            rating_digit = t_val
                                            break

                            # 排除法核心變數初始化
                            is_excluded = False
                            exclusion_reason = ""
                            min_rate = 0
                            max_rate = 0
                            potential_status = "無本地賽績數據"
                            has_real_injury = False
                            is_new_horse = True
                            
                            latest_top3_dt = None
                            latest_injury_dt = None

                            if not db_records.empty:
                                horse_history_races = db_records[
                                    db_records['馬名'] == pure_horse_name
                                ].copy()
                                if not horse_history_races.empty:
                                    is_new_horse = False 
                                    def clean_p(x):
                                        try: return int(str(x).strip())
                                        except: return 99
                                    horse_history_races['名次_數'] = \
                                        horse_history_races['名次'] \
                                        .apply(clean_p)
                                    top3_history = horse_history_races[
                                        horse_history_races['名次_數'] <= 3
                                    ].copy()
                                    
                                    if not top3_history.empty:
                                        min_rate = int(pd.to_numeric(
                                            top3_history['評分'], 
                                            errors='coerce').min())
                                        max_rate = int(pd.to_numeric(
                                            top3_history['評分'], 
                                            errors='coerce').max())
                                        
                                        top3_history['dt'] = pd.to_datetime(
                                            top3_history['日期'], 
                                            errors='coerce', dayfirst=True
                                        )
                                        valid_top3 = top3_history.dropna(subset=['dt'])
                                        if not valid_top3.empty:
                                            latest_top3_dt = valid_top3['dt'].max()
                                    
                                    recent_3 = horse_history_races.tail(3)
                                    has_top3_recently = any(
                                        clean_p(r['名次']) <= 3 
                                        for _, r in recent_3.iterrows()
                                    )
                                    if has_top3_recently or \
                                       (rating_digit.isdigit() and \
                                        int(rating_digit) >= max_rate):
                                        potential_status = "📈 平穩向上"
                                    else:
                                        potential_status = "📉 飽和調整期"

                            if is_new_horse and not db_injuries.empty:
                                if not db_injuries[db_injuries['馬名'] == \
                                   pure_horse_name].empty:
                                    is_new_horse = False

                            if not db_injuries.empty:
                                horse_injuries = db_injuries[
                                    db_injuries['馬名'] == pure_horse_name
                                ].copy()
                                if not horse_injuries.empty:
                                    horse_injuries['dt'] = pd.to_datetime(
                                        horse_injuries['傷患日期'], 
                                        errors='coerce', dayfirst=True
                                    )
                                    for _, inj_row in horse_injuries.iterrows():
                                        detail_text = str(inj_row['詳情'])
                                        if any(kw in detail_text 
                                               for kw in real_injury_keywords) \
                                           and not any(ekw in detail_text 
                                               for ekw in exclusion_keywords):
                                            
                                            has_real_injury = True
                                            if pd.notna(inj_row['dt']):
                                                if latest_injury_dt is None or \
                                                   inj_row['dt'] > latest_injury_dt:
                                                    latest_injury_dt = inj_row['dt']

                            if has_real_injury and latest_top3_dt is not None \
                               and latest_injury_dt is not None:
                                if latest_top3_dt > latest_injury_dt:
                                    has_real_injury = False 

                            # -------------------------------------------------
                            # 🛡️ 智能四重篩選排除防線判定 (純日期推算馬季版)
                            # -------------------------------------------------
                            if has_real_injury:
                                is_excluded = True
                                exclusion_reason = "❌ 排除：本地庫查出有嚴重生理傷患紀錄！"
                            elif rating_digit.isdigit() and max_rate > 0:
                                current_rating_val = int(rating_digit)
                                if current_rating_val > (max_rate + 2) and \
                                   potential_status not in ["🌱 成長中", 
                                                            "📈 平穩向上"]:
                                    is_excluded = True
                                    exclusion_reason = f"❌ 排除：現時評分" \
                                        f"({current_rating_val}分)高過黃金頂峰" \
                                        f"({max_rate}分)阻力過大。"
                            elif is_new_horse and \
                                 trainer_clean in black_trainers:
                                is_excluded = True
                                exclusion_reason = f"❌ 排除：此馬為" \
                                    f"[🆕新馬/插班馬]，且所屬馬房" \
                                    f"【{trainer_clean}】已列入冷門名單。"

                            # 💡 ✨ 核心升級：利用【日期欄位】完美推算 25/26 馬季出賽，徹底擺脫對季度欄位的依賴
                            if not is_excluded and not is_new_horse and not horse_history_races.empty:
                                try:
                                    # 先將歷史賽績中的「日期」統一轉換為時間物件
                                    horse_history_races['r_dt'] = pd.to_datetime(
                                        horse_history_races['日期'], errors='coerce', dayfirst=True
                                    )
                                    
                                    # 篩選 25/26 馬季的比賽條件：
                                    # 條件一：2025年 9月至12月
                                    cond_2025 = (horse_history_races['r_dt'].dt.year == 2025) & (horse_history_races['r_dt'].dt.month >= 9)
                                    # 條件二：2026年 1月至7月
                                    cond_2026 = (horse_history_races['r_dt'].dt.year == 2026) & (horse_history_races['r_dt'].dt.month <= 7)
                                    
                                    # 執行精確馬季過濾
                                    season_races = horse_history_races[cond_2025 | cond_2026]
                                    
                                    if len(season_races) > 5:
                                        season_top3 = season_races[season_races['名次_數'] <= 3]
                                        if len(season_top3) == 0:
                                            age_val = season_races.iloc[-1].get('當前年齡', 5)
                                            try: horse_age_int = int(float(str(age_val).strip()))
                                            except: horse_age_int = 5
                                            
                                            is_excluded = True
                                            if horse_age_int >= 6:
                                                exclusion_reason = f"❌ 排除：25/26季出賽{len(season_races)}場未曾上名，且({horse_age_int}歲)退化老馬。"
                                            else:
                                                exclusion_reason = f"❌ 排除：25/26季出賽{len(season_races)}場未曾上名，且({horse_age_int}歲)能力不足。"
                                except: pass

                            if not is_excluded:
                                recommend_numbers.append(num)

                            if min_rate > 0:
                                gold_label = f"{min_rate}-{max_rate}分"
                            elif is_new_horse:
                                gold_label = "🆕 新馬/插班馬"
                            else:
                                gold_label = "📉 查有賽績/未曾上名"


                            race_horses.append({
                                'num': num, 'history': history, 
                                'name': horse_name_display,
                                'weight': weight_digit + " 磅" \
                                          if weight_digit else "134 磅",
                                'jockey': jockey_clean, 'draw': draw_digit \
                                          + " 檔" if draw_digit else "-",
                                'trainer': trainer_clean, 
                                'rating': rating_digit,
                                'is_excluded': is_excluded, 
                                'exclusion_reason': exclusion_reason,
                                'gold_range': gold_label
                            })
                        except Exception: continue
                
                if recommend_numbers:
                    recommend_str = ", ".join(sorted(recommend_numbers, 
                                              key=int))
                            
    except Exception as e:
        race_details['title'] = f"⚠️ 連線失敗: {str(e)}"

    print("\n" + "✍️  "*15 + "【人手輸入指令控制台】" + " ✍️ "*15)
    print(f"📅 閣下指令日子：{target_date}")
    print(f"🏟️ 閣下指令馬場：{venue_code} (ST=沙田, HV=跑馬地)")
    print(f"🏁 當前載入顯示：第 {race_no} 場賽事完整排位陣容")
    print(f"🌟 本場精選推薦：{recommend_str}")
    print("="*80 + "\n")

    return render_template('hkjc_live.html', 
                           race_horses=race_horses, 
                           current_race=race_no, 
                           race_details=race_details, 
                           race_date_str=race_date_str,
                           venue_code=venue_code,
                           recommend_str=recommend_str, 
                           races=list(range(1, 11)))
