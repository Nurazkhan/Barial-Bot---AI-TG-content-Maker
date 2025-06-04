import sqlite3

DB_PATH = "channels.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                userid INTEGER,
                channel_username TEXT,
                channel_type TEXT,
                active INTEGER DEFAULT 1,
                UNIQUE(userid, channel_username, channel_type)
            )
        """)

def add_channel(userid, username, ch_type):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO channels (userid, channel_username, channel_type, active) VALUES (?, ?, ?, 1)",
            (userid, username, ch_type)
        )

def get_channels(userid, ch_type=None, only_active=False):
    with sqlite3.connect(DB_PATH) as conn:
        q = "SELECT channel_username FROM channels WHERE userid=?"
        params = [userid]
        if ch_type:
            q += " AND channel_type=?"
            params.append(ch_type)
        if only_active:
            q += " AND active=1"
        return [row[0] for row in conn.execute(q, params)]

def get_user_channels(userid):
    with sqlite3.connect(DB_PATH) as conn:
        data = {"listen": [], "send": []}
        for ch_type in ("listen", "send"):
            rows = conn.execute(
                "SELECT channel_username, active FROM channels WHERE userid=? AND channel_type=?",
                (userid, ch_type)
            )
            data[ch_type] = [{"channel": r[0], "active": bool(r[1])} for r in rows]
        return data

def update_channel_status(userid, username, ch_type, active):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE channels SET active=? WHERE userid=? AND channel_username=? AND channel_type=?",
            (int(active), userid, username, ch_type)
        )

def get_all_user_ids():
    with sqlite3.connect(DB_PATH) as conn:
        return [row[0] for row in conn.execute("SELECT DISTINCT userid FROM channels")]
    
def get_all_active_listening_channels():
    with sqlite3.connect(DB_PATH) as conn:
        return [row[0] for row in conn.execute("SELECT DISTINCT channel_username FROM channels WHERE channel_type='listen' AND active=1")]
def init_group_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS channel_groups (
                userid INTEGER,
                group_name TEXT,
                group_type TEXT DEFAULT 'send',
                UNIQUE(userid, group_name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS group_channels (
                userid INTEGER,
                group_name TEXT,
                channel_username TEXT,
                UNIQUE(userid, group_name, channel_username)
            )
        """)
        # Migration: add group_type if missing
        try:
            conn.execute("ALTER TABLE channel_groups ADD COLUMN group_type TEXT DEFAULT 'send'")
        except sqlite3.OperationalError:
            pass  # already exists

def create_group(userid, group_name, group_type):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO channel_groups (userid, group_name, group_type) VALUES (?, ?, ?)",
            (userid, group_name, group_type)
        )

def get_groups(userid, with_type=False):
    with sqlite3.connect(DB_PATH) as conn:
        if with_type:
            return [(row[0], row[1]) for row in conn.execute(
                "SELECT group_name, group_type FROM channel_groups WHERE userid=?", (userid,)
            )]
        else:
            return [row[0] for row in conn.execute(
                "SELECT group_name FROM channel_groups WHERE userid=?", (userid,)
            )]

def add_channel_to_group(userid, group_name, channel_username):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO group_channels (userid, group_name, channel_username) VALUES (?, ?, ?)",
            (userid, group_name, channel_username)
        )

def remove_channel_from_group(userid, group_name, channel_username):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM group_channels WHERE userid=? AND group_name=? AND channel_username=?",
            (userid, group_name, channel_username)
        )

def get_group_channels(userid, group_name):
    with sqlite3.connect(DB_PATH) as conn:
        return [row[0] for row in conn.execute(
            "SELECT channel_username FROM group_channels WHERE userid=? AND group_name=?",
            (userid, group_name)
        )]

def delete_group(userid, group_name):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM channel_groups WHERE userid=? AND group_name=?",
            (userid, group_name)
        )
        conn.execute(
            "DELETE FROM group_channels WHERE userid=? AND group_name=?",
            (userid, group_name)
        )

def init_ai_settings_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_settings (
                userid INTEGER PRIMARY KEY,
                prompt_template TEXT
            )
        """)

def set_user_prompt(userid, prompt):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO ai_settings (userid, prompt_template) VALUES (?, ?)",
            (userid, prompt)
        )

def get_user_prompt(userid):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT prompt_template FROM ai_settings WHERE userid=?",
            (userid,)
        ).fetchone()
        return row[0] if row else None

def init_connections_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS connections (
                userid INTEGER,
                listen_group TEXT,
                send_group TEXT,
                connection_name TEXT,
                automate INTEGER DEFAULT 0,
                UNIQUE(userid, connection_name)
            )
        ''')

def add_connection(userid, listen_group, send_group, connection_name):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO connections (userid, listen_group, send_group, connection_name) VALUES (?, ?, ?, ?)",
            (userid, listen_group, send_group, connection_name)
        )

def get_connections(userid):
    with sqlite3.connect(DB_PATH) as conn:
        return [dict(listen_group=row[0], send_group=row[1], connection_name=row[2], automate=row[3])
                for row in conn.execute(
            "SELECT listen_group, send_group, connection_name, automate FROM connections WHERE userid=?",
            (userid,))]

def set_automation(userid, connection_name, automate):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE connections SET automate=? WHERE userid=? AND connection_name=?",
            (int(automate), userid, connection_name)
        )

def get_connection_by_name(userid, connection_name):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT listen_group, send_group, automate FROM connections WHERE userid=? AND connection_name=?",
            (userid, connection_name)
        ).fetchone()
        if row:
            return dict(listen_group=row[0], send_group=row[1], automate=row[2])
        return None

def get_connection_for_channel(userid, channel_username):
    # Returns all connections where channel_username is in the listen group
    with sqlite3.connect(DB_PATH) as conn:
        return [dict(listen_group=row[0], send_group=row[1], connection_name=row[2], automate=row[3])
                for row in conn.execute(
            "SELECT c.listen_group, c.send_group, c.connection_name, c.automate FROM connections c "
            "JOIN group_channels g ON c.userid=g.userid AND c.listen_group=g.group_name "
            "WHERE c.userid=? AND g.channel_username=?",
            (userid, channel_username))]