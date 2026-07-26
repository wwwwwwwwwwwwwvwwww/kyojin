import sqlite3, json

conn = sqlite3.connect('securitybot.db')

try:
    conn.execute("ALTER TABLE guild_settings ADD COLUMN join_gif TEXT NOT NULL DEFAULT 'https://i.imgur.com/a2rksjN.gif'")
    conn.commit()
    print('Added join_gif column')
except Exception as e:
    print(f'join_gif: {e}')

try:
    conn.execute("ALTER TABLE guild_settings ADD COLUMN leave_gif TEXT NOT NULL DEFAULT 'https://i.imgur.com/K7aaTLk.gif'")
    conn.commit()
    print('Added leave_gif column')
except Exception as e:
    print(f'leave_gif: {e}')

c = conn.execute('SELECT guild_id, antinuke FROM guild_settings')
rows = c.fetchall()
for row in rows:
    raw = row[1]
    data = json.loads(raw) if isinstance(raw, str) else {}
    changed = False
    events = data.get('events', {})
    for ek, ev in events.items():
        if ev is True or ev is False:
            events[ek] = {'enabled': bool(ev), 'threshold': 1, 'punishment': 'strip'}
            changed = True
    if changed:
        data['events'] = events
        conn.execute('UPDATE guild_settings SET antinuke=? WHERE guild_id=?', (json.dumps(data), row[0]))
        conn.commit()
        print('Converted events to dicts')

c = conn.execute('SELECT * FROM guild_settings')
cols = [x[0] for x in c.description]
for r in c.fetchall():
    d = dict(zip(cols, r))
    an = json.loads(d.get('antinuke','{}'))
    print('Columns:', cols)
    print('Event types:', {k: type(v).__name__ for k,v in an.get('events',{}).items()})
    print('Sample event:', an.get('events',{}).get('ban'))
    print('join_gif:', d.get('join_gif','MISSING'))
    print('leave_gif:', d.get('leave_gif','MISSING'))
    break

conn.close()
print('Done')
