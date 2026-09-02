"""
This script runs the HorseRacingAnalysis application using a development server.
"""
import os
from HorseRacingAnalysis import app # 確保指向您的 Flask app 實例

# 💡 Vercel 需要讀取名為 app 或 application 的變數
app = app 

if __name__ == '__main__':
    HOST = os.environ.get('SERVER_HOST', 'localhost')
    try:
        PORT = int(os.environ.get('SERVER_PORT', '5555'))
    except ValueError:
        PORT = 5555
    app.run(HOST, PORT)
