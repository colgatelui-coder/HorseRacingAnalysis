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
    """AI 分析引擎"""
    conn = sqlite3.connect(DB_FILE)
    try:
        df_races = pd.read_sql_query("SELECT * FROM racing_records", conn)
        df_injuries = pd.read_sql_query("SELECT * FROM injury_records", conn)
        conn.close()
        
        if df_races.empty: return [], None

        def clean_place(x):
            try: return int(str(x).strip())
            except: return None

        df_races['名次_數字'] = df_races['名次'].apply(clean_place)
        df_races['評分_數字'] = pd.to_numeric(df_races['評分'], errors='coerce')
        df_races['途程_米'] = pd.to_numeric(df_races['途程_米'], errors='coerce')
        df_races['季度場次'] = pd.to_numeric(df_races['季度場次'], errors='coerce')

        top_3_df = df_races[df_races['名次_數字'] <= 3].dropna(subset=['評分_數字'])
        results = []
        unique_horses = df_races['馬名'].unique()

        real_injury_keywords = ['心律', '流血', '不良於行', '受傷', '手術', '肌腱', '筋腱', '懸韌帶', '韌帶', '骨', '關節', '碎骨', '呼吸道', '喘鳴症', '流鼻血']
        exclusion_keywords = ['表現欠佳', '令人失望', '難以接受', '八歲或以上', '食慾不振', '發燒', '閹割', '煩躁', '被卡住', '隔鄰', '隔壁', '拋下']

        for horse in unique_horses:
            horse_all = df_races[df_races['馬名'] == horse].sort_values(by='季度場次', ascending=True)
            horse_top3 = top_3_df[top_3_df['馬名'] == horse]
            
            if len(horse_top3) == 0: continue

            min_rate = int(horse_top3['評分_數字'].min())
            max_rate = int(horse_top3['評分_數字'].max())
            best_dist = int(horse_top3['途程_米'].value_counts().idxmax())
            
            latest_row = horse_all.iloc[-1]
            if pd.isna(latest_row['評分_數字']): continue
            latest_rating = int(latest_row['評分_數字'])
            horse_age = int(latest_row['當前年齡']) if not pd.isna(latest_row['當前年齡']) else 5

            horse_injuries = df_injuries[df_injuries['馬名'] == horse]
            has_real_injury = False
            injury_detail = ""

            if not horse_injuries.empty:
                for _, injury_row in horse_injuries.iterrows():
                    detail_text = str(injury_row['詳情'])
                    contains_injury = any(kw in detail_text for kw in real_injury_keywords)
                    contains_exclusion = any(kw in detail_text for kw in exclusion_keywords)
                    if contains_injury and not contains_exclusion:
                        has_real_injury = True
                        injury_detail = detail_text
                        break

            recent_3_races = horse_all.dropna(subset=['評分_數字', '名次_數字']).tail(3)
            recent_3_ratings = recent_3_races['評分_數字'].tolist()
            recent_3_places = recent_3_races['名次_數字'].tolist()
            
            has_rating_near_high = any(rating >= (max_rate - 2) for rating in recent_3_ratings)
            has_top3_recently = any(place <= 3 for place in recent_3_places)

            if has_rating_near_high and has_top3_recently and not has_real_injury:
                if horse_age <= 5:
                    potential_status = "🌱 成長中 (戰力再突破)"
                    potential_color = "success"
                    potential_desc = f"({horse_age}歲) 年輕進步馬！近3場有上名且逼近最高評分，無生理傷患隱憂。"
                else:
                    potential_status = "📈 平穩向上 (老當益壯)"
                    potential_color = "info"
                    potential_desc = f"({horse_age}歲) 熟齡大勇！近3場交出上名且維持高位評分，體態健康。"
            elif has_real_injury:
                potential_status = "🩹 傷患隱憂 (謹慎觀望)"
                potential_color = "dark"
                potential_desc = f"⚠️ 跨表查出該馬有嚴重生理傷患：【{injury_detail}】！建議防守觀望。"
            else:
                if horse_age <= 5:
                    potential_status = "💤 成長調整中"
                    potential_color = "warning"
                    potential_desc = "年輕生力軍，目前評分適度回落，正儲備下次反彈能量。"
                else:
                    potential_status = "🏔️ 已達最高頂峰"
                    potential_color = "danger"
                    potential_desc = "黃金大賽期老手，目前評分與表現已達天花板，再突破空間有限。"

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
                'range': f"{min_rate} - {max_rate} 分", 'dist': f"{best_dist}米",
                'current': latest_rating, 'status': status, 'color': badge_color, 'desc': desc,
                'potential': potential_status, 'potential_color': potential_color, 'potential_desc': potential_desc,
                'injury': "🚨 有嚴重傷患" if has_real_injury else "🟢 健康無礙",
                'injury_alert': has_real_injury, 'injury_text': injury_detail
            })
        return results, None
    except Exception as e:
        if conn: conn.close()
        return [], f"SQL 跨表運算失敗: {str(e)}"

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
    """2. 萬能動態排位解碼引擎：完全依照人手指定之日期與場地進行即時加載"""
    # 將網址路徑中的橫線還原為馬會網址所需的斜線
    target_date = race_date_str.replace('-', '/')
    
    # 💡 後台 printf 即時列印人手輸入驗證日誌
    print("\n" + "✍️  "*15 + "【人手輸入指令控制台】" + " ✍️ "*15)
    print(f"📅 閣下指令日子：{target_date}")
    print(f"🏟️ 閣下指令馬場：{venue_code} (ST=沙田, HV=跑馬地)")
    print(f"🏁 當前載入顯示：第 {race_no} 場賽事完整排位陣容")
    print("="*80 + "\n")
    
    # 拼接馬會官方最新排位網址
    url = f"https://racing.hkjc.com/zh-hk/local/information/racecard?racedate={target_date}&Racecourse={venue_code}&RaceNo={race_no}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    race_horses = []
    race_details = {
        'title': f"第 {race_no} 場 賽事排位",
        'datetime': f"{target_date} 人手指定賽期",
        'track': f"{'沙田馬場' if venue_code == 'ST' else '跑馬地馬場'} | 草地",
        'class_prize': "數據讀取中..."
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 全網純文字地毯式掃描賽事詳情
            global_pure_text = "".join(soup.text.split())
            track_match = re.search(r'(草地,.*?\d+米|草地.*?賽道\d+米|\d+米)', " ".join(soup.text.split()))
            if track_match: race_details['track'] = track_match.group(1).strip()
            
            class_match = re.search(r'(第[\u4e00-\u9fa5一二三四五六]班)', global_pure_text)
            if class_match:
                prize_match = re.search(r'(獎金:\$\d+,\d+,\d+|獎金:\$\d+,\d+)', global_pure_text)
                prize_str = prize_match.group(1) + " | " if prize_match else ""
                race_details['class_prize'] = f"{prize_str}{class_match.group(1)}"

            title_match = re.search(r'(第\d+場-[\u4e00-\u9fa5]+讓賽)', global_pure_text)
            if title_match: race_details['title'] = title_match.group(1)

            # 解析下方表格數據 (維持原本無瑕疵 1:1 黃金對位引擎)
            table = soup.find('table', id='racecardlist') or soup.find('table', class_='table_bd')
            if table:
                rows = table.find_all('tr')
                idx_map = {'num': 0, 'history': 1, 'name': 3, 'weight': 5, 'jockey': 6, 'draw': 7, 'trainer': 8, 'rating': 9}
                
                header_tr = table.find('tr', class_='table_header') or table.find('tr')
                if header_tr:
                    th_list = header_tr.find_all(['th', 'td'])
                    for i, th in enumerate(th_list):
                        th_text = th.text.strip()
                        if '馬匹編號' in th_text or '馬號' in th_text: idx_map['num'] = i
                        elif '近績' in th_text: idx_map['history'] = i
                        elif '馬名' in th_text: idx_map['name'] = i
                        elif '負磅' in th_text: idx_map['weight'] = i
                        elif '騎師' in th_text: idx_map['jockey'] = i
                        elif '檔位' in th_text: idx_map['draw'] = i
                        elif '練馬師' in th_text: idx_map['trainer'] = i
                        elif '評分' in th_text: idx_map['rating'] = i

                for row in rows:
                    if row.find('th') or 'table_header' in str(row.get('class', '')) or 'hidden' in str(row.get('class', '')):
                        continue
                    
                    cols = row.find_all('td')
                    if len(cols) >= 10:
                        try:
                            num_text = cols[idx_map['num']].text.strip()
                            num_match = re.search(r'\d+', num_text)
                            if not num_match: continue
                            num = num_match.group(0)
                            
                            history = " ".join(cols[idx_map['history']].text.split()).strip()
                            raw_name = " ".join(cols[idx_map['name']].text.split()).strip()
                            name_match = re.search(r'([\u4e00-\u9fa5]+)\s*\(([A-Z0-9]+)\)', raw_name)
                            horse_name = f"{name_match.group(1)} [{name_match.group(2)}]" if name_match else raw_name

                            weight_digit = "".join(filter(str.isdigit, cols[idx_map['weight']].text.strip()))
                            jockey_clean = " ".join(cols[idx_map['jockey']].text.split()).strip().replace('\n', '')

                            if "綵衣" in horse_name or "負磅" in jockey_clean or "騎師" in jockey_clean: continue

                            raw_draw = cols[idx_map['draw']].text.strip()
                            draw_digit = "".join(filter(str.isdigit, raw_draw))
                            if not draw_digit and idx_map['draw'] + 1 < len(cols):
                                draw_digit = "".join(filter(str.isdigit, cols[idx_map['draw'] + 1].text.strip()))

                            trainer_idx = idx_map['trainer'] + 1 if idx_map['trainer'] + 1 < len(cols) else idx_map['trainer']
                            raw_trainer = " ".join(cols[trainer_idx].text.split()).strip()
                            trainer_clean = "".join(re.findall(r'[\u4e00-\u9fa5]+', raw_trainer.replace('\n', ''))).replace("檔", "")

                            rating_digit = "-"
                            for cell in cols:
                                cell_class = str(cell.get('class', '')).lower()
                                if 'rating' in cell_class and cell.text.strip().isdigit():
                                    rating_digit = cell.text.strip()
                                    break
                            if rating_digit == "-":
                                for idx_check in range(idx_map['trainer'], len(cols)):
                                    t_val = cols[idx_check].text.strip()
                                    if t_val.isdigit() and t_val != num and t_val != draw_digit:
                                        if int(t_val) != 1 or idx_check == idx_map['rating'] or idx_check == idx_map['rating'] + 1:
                                            rating_digit = t_val
                                            break

                            race_horses.append({
                                'num': num, 'history': history, 'name': horse_name,
                                'weight': weight_digit + " 磅" if weight_digit else "134 磅",
                                'jockey': jockey_clean if jockey_clean else "待定",
                                'draw': draw_digit + " 檔" if draw_digit else "-",
                                'trainer': trainer_clean if trainer_clean else "待定", 'rating': rating_digit
                            })
                        except Exception: continue
                            
    except Exception as e:
        race_details['title'] = f"⚠️ 連線失敗: {str(e)}"

    # 💡 傳遞動態路由專用的變數給 HTML，好讓第1場到第10場的按鈕能正確切換網址
    return render_template('hkjc_live.html', 
                           race_horses=race_horses, 
                           current_race=race_no, 
                           race_details=race_details, 
                           race_date_str=race_date_str,
                           venue_code=venue_code,
                           races=list(range(1, 11)))