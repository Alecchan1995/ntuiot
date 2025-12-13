#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESP32 貨架監控系統 - RPI 數據處理中心
功能：接收 ESP32 感測器數據、判斷邏輯、數據庫儲存
"""

import paho.mqtt.client as mqtt
import json
import datetime
import time
import sqlite3
from pathlib import Path
import iot_firebase_pb

# ==================== MQTT 設定 ====================
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60

TOPIC_SENSOR = "shelf/sensor"
TOPIC_STATUS = "shelf/status"
TOPIC_COMMAND = "shelf/command"

# ==================== 數據庫設定 ====================
DB_FILE = "shelf_data.db"

# ==================== 貨架配置 ====================
# 貨架尺寸配置（與 ESP32 對應）
# 單感測器模式：使用最大距離來判斷是否有物品
SHELF_CONFIG = {
    "A1": {"max_distance": 30.0},  # 最大距離 25cm
    "A2": {"max_distance": 30.0},  # 最大距離 30cm
    "B1": {"max_distance": 20.0}   # 最大距離 20cm
}

# ==================== 顏色代碼 ====================
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

# ==================== 數據庫初始化 ====================
def init_database():
    """初始化 SQLite 數據庫"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # 建立感測器數據表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sensor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shelf_id TEXT NOT NULL,
            distance_cm REAL NOT NULL,
            occupied INTEGER NOT NULL,
            fill_percent REAL NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 建立索引以加速查詢
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_shelf_id 
        ON sensor_data(shelf_id)
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_timestamp 
        ON sensor_data(timestamp)
    ''')
    
    conn.commit()
    conn.close()
    
    print(f"{Colors.OKGREEN}[數據庫]{Colors.ENDC} 數據庫初始化完成: {DB_FILE}")

# ==================== 判斷邏輯 ====================
def analyze_shelf_data(shelf_id, distance_cm):
    """
    分析貨架數據（單感測器模式）
    返回: (occupied, fill_percent)
    
    判斷邏輯：
    - 距離越小 = 物品越多
    - 填充率 = (最大距離 - 實際距離) / 最大距離 × 100%
    """
    if shelf_id not in SHELF_CONFIG:
        return False, 0.0
    
    config = SHELF_CONFIG[shelf_id]
    max_distance = config["max_distance"]
    
    # 計算物品佔用的空間（公分）
    occupied_space = max_distance - distance_cm
    
    # 判斷是否有物品（佔用空間 > 2cm 就算有物品）
    # 即：檢測距離小於最大距離 2cm 以上就判定為有貨
    if occupied_space > 2.0:
        occupied = True
        fill_percent = (occupied_space / max_distance) * 100.0
        
        # 限制在 0-100%
        fill_percent = max(0.0, min(100.0, fill_percent))
    else:
        occupied = False
        fill_percent = 0.0
    
    return occupied, fill_percent

# ==================== 數據庫儲存 ====================
def save_to_database(shelf_id, distance_cm, occupied, fill_percent):
    """儲存數據到數據庫"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # 使用當前時間作為時間戳記
        current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        cursor.execute('''
            INSERT INTO sensor_data 
            (shelf_id, distance_cm, occupied, fill_percent, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (shelf_id, distance_cm, int(occupied), fill_percent, current_time))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"{Colors.FAIL}[錯誤]{Colors.ENDC} 數據庫儲存失敗: {e}")
        return False

# ==================== MQTT 回調函式 ====================
def on_connect(client, userdata, flags, rc):
    """當連接到 MQTT broker 時的回調"""
    if rc == 0:
        print(f"{Colors.OKGREEN}[MQTT]{Colors.ENDC} 已連接到 MQTT Broker")
        
        # 訂閱主題
        client.subscribe(TOPIC_SENSOR)
        print(f"{Colors.OKCYAN}[訂閱]{Colors.ENDC} {TOPIC_SENSOR}")
        
        client.subscribe(TOPIC_STATUS)
        print(f"{Colors.OKCYAN}[訂閱]{Colors.ENDC} {TOPIC_STATUS}")
        
        print(f"\n{Colors.BOLD}{'='*60}{Colors.ENDC}")
        print(f"{Colors.BOLD}RPI 數據處理中心已啟動{Colors.ENDC}")
        print(f"{Colors.BOLD}{'='*60}{Colors.ENDC}\n")
    else:
        print(f"{Colors.FAIL}[錯誤]{Colors.ENDC} 連線失敗，錯誤碼: {rc}")

def on_message(client, userdata, msg):
    """當收到訊息時的回調"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    topic = msg.topic
    payload = msg.payload.decode('utf-8')
    
    if topic == TOPIC_SENSOR:
        handle_sensor_message(payload, timestamp)
    elif topic == TOPIC_STATUS:
        handle_status_message(payload, timestamp)

def handle_sensor_message(payload, timestamp):
    """處理感測器數據訊息"""
    try:
        # 解析 JSON 數據
        data = json.loads(payload)
        
        shelf_id = data.get('shelf_id', 'N/A')
        distance_cm = data.get('distance_cm', -1)
        
        # 檢查數據是否有效（距離 -1 表示感測器讀取失敗）
        if distance_cm == -1 or distance_cm < 0:
            print(f"\n{Colors.HEADER}[{timestamp}]{Colors.ENDC}")
            print(f"{Colors.WARNING}[無效數據]{Colors.ENDC} 貨架: {Colors.BOLD}{shelf_id}{Colors.ENDC}")
            print(f"  距離: {Colors.FAIL}{distance_cm} cm (無效){Colors.ENDC}")
            print(f"  原因: 感測器讀取失敗或超出範圍")
            print(f"  ✗ 此筆數據已忽略，不儲存到數據庫")
            return
        
        # 判斷邏輯
        occupied, fill_percent = analyze_shelf_data(shelf_id, distance_cm)
        
        # 儲存到數據庫（使用 RPI 當前時間）
        save_to_database(shelf_id, distance_cm, occupied, fill_percent)
        
        # 顯示結果
        print(f"\n{Colors.HEADER}[{timestamp}]{Colors.ENDC}")
        print(f"{Colors.OKBLUE}[感測器數據]{Colors.ENDC} 貨架: {Colors.BOLD}{shelf_id}{Colors.ENDC}")
        print(f"  距離: {distance_cm:.1f} cm")
        
        if occupied:
            print(f"  狀態: {Colors.OKGREEN}有物品{Colors.ENDC}")
            print(f"  填充率: {Colors.OKGREEN}{fill_percent:.1f}%{Colors.ENDC}")
        else:
            print(f"  狀態: {Colors.WARNING}空的{Colors.ENDC}")
            print(f"  填充率: 0%")
        
        print(f"  ✓ 已儲存到數據庫")
        
    except json.JSONDecodeError as e:
        print(f"{Colors.FAIL}[錯誤]{Colors.ENDC} JSON 解析失敗: {e}")
    except Exception as e:
        print(f"{Colors.FAIL}[錯誤]{Colors.ENDC} 處理數據失敗: {e}")

def handle_status_message(payload, timestamp):
    """處理狀態訊息"""
    print(f"\n{Colors.HEADER}[{timestamp}]{Colors.ENDC}")
    print(f"{Colors.OKBLUE}[ESP32 狀態]{Colors.ENDC}")
    
    try:
        data = json.loads(payload)
        print(f"  WiFi: {data.get('wifi', 'N/A')}")
        print(f"  MQTT: {data.get('mqtt', 'N/A')}")
        
        # 將 uptime_ms 轉換為可讀格式
        uptime_ms = data.get('uptime_ms', 0)
        uptime_seconds = uptime_ms / 1000
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        seconds = int(uptime_seconds % 60)
        print(f"  運行時間: {hours:02d}:{minutes:02d}:{seconds:02d}")
        
        print(f"  貨架數量: {data.get('shelf_count', 'N/A')}")
    except json.JSONDecodeError:
        print(f"  訊息: {payload}")

# ==================== 查詢函式 ====================
def query_latest_data(shelf_id=None, limit=10):
    """查詢最新數據"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    if shelf_id:
        cursor.execute('''
            SELECT shelf_id, distance_cm, occupied, fill_percent, timestamp
            FROM sensor_data
            WHERE shelf_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (shelf_id, limit))
    else:
        cursor.execute('''
            SELECT shelf_id, distance_cm, occupied, fill_percent, timestamp
            FROM sensor_data
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return rows

# ==================== 主程式 ====================
def main():
    print(f"{Colors.BOLD}{Colors.HEADER}")
    print("╔════════════════════════════════════════════════════════╗")
    print("║       ESP32 貨架監控系統 - RPI 數據處理中心           ║")
    print("╚════════════════════════════════════════════════════════╝")
    print(f"{Colors.ENDC}")
    
    # 初始化數據庫
    init_database()
    
    # 建立 MQTT 客戶端
    client = mqtt.Client(client_id="RPI_DataCenter")
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        # 連接到 MQTT Broker
        print(f"正在連接到 MQTT Broker ({MQTT_BROKER}:{MQTT_PORT})...")
        client.connect(MQTT_BROKER, MQTT_PORT, MQTT_KEEPALIVE)
        
        print("提示：按 Ctrl+C 可以停止程式\n")
        
        # 開始循環處理
        client.loop_forever()
        
    except KeyboardInterrupt:
        print(f"\n\n{Colors.WARNING}[使用者中斷]{Colors.ENDC} 正在關閉...")
    except Exception as e:
        print(f"\n{Colors.FAIL}[錯誤]{Colors.ENDC} {e}")
    finally:
        client.disconnect()
        print(f"{Colors.OKGREEN}[已斷線]{Colors.ENDC} 程式結束")

if __name__ == "__main__":
    main()

