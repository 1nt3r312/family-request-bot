import sqlite3
import json

def init_db():
    conn = sqlite3.connect('family_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id TEXT PRIMARY KEY,
            role_id TEXT,
            channel_id TEXT,
            member_role_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def get_guild_settings(guild_id):
    conn = sqlite3.connect('family_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM guild_settings WHERE guild_id = ?', (str(guild_id),))
    result = cursor.fetchone()
    
    conn.close()
    
    if result:
        return {
            'guild_id': result[0],
            'role_id': result[1],
            'channel_id': result[2],
            'member_role_id': result[3]
        }
    return None

def set_guild_settings(guild_id, role_id=None, channel_id=None, member_role_id=None):
    conn = sqlite3.connect('family_bot.db')
    cursor = conn.cursor()
    
    # Получаем текущие настройки
    current = get_guild_settings(guild_id) or {}
    
    # Обновляем только переданные значения
    new_role_id = role_id if role_id else current.get('role_id')
    new_channel_id = channel_id if channel_id else current.get('channel_id')  
    new_member_role_id = member_role_id if member_role_id else current.get('member_role_id')
    
    cursor.execute('''
        INSERT OR REPLACE INTO guild_settings 
        (guild_id, role_id, channel_id, member_role_id) 
        VALUES (?, ?, ?, ?)
    ''', (str(guild_id), str(new_role_id), str(new_channel_id), str(new_member_role_id)))
    
    conn.commit()
    conn.close()