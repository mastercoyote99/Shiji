"""Local storage, additive migrations, extraction and outbound source gate."""
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
FILES = DATA / 'files'
DB = DATA / 'shiji.db'

@contextmanager
def connect():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    try:
        with c:
            yield c
    finally:
        c.close()

def initialize():
    FILES.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS items (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, space TEXT NOT NULL,
          tags TEXT NOT NULL, body TEXT NOT NULL, url TEXT NOT NULL,
          filename TEXT NOT NULL, stored_name TEXT NOT NULL, created_at TEXT NOT NULL)''')
        columns = {r['name'] for r in c.execute('PRAGMA table_info(items)')}
    additions = {'local_only':'INTEGER NOT NULL DEFAULT 1',
                 'deleted':'INTEGER NOT NULL DEFAULT 0',
                 'revision':'INTEGER NOT NULL DEFAULT 1',
                 'sha256':"TEXT NOT NULL DEFAULT ''",
                 'extract_status':"TEXT NOT NULL DEFAULT '待处理'"}
    if set(additions) - columns:
        backup = DATA / ('before_v03_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.db')
        with connect() as source:
            dest = sqlite3.connect(backup)
            try: source.backup(dest)
            finally: dest.close()
    with connect() as c:
        for name, declaration in additions.items():
            if name not in columns: c.execute(f'ALTER TABLE items ADD COLUMN {name} {declaration}')
        c.execute('''CREATE TABLE IF NOT EXISTS extracted_pages (
          item_id TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL,
          PRIMARY KEY(item_id,page))''')
        c.execute('''CREATE TABLE IF NOT EXISTS chunks_v03 (
          id TEXT PRIMARY KEY, item_id TEXT NOT NULL, page INTEGER NOT NULL,
          offset INTEGER NOT NULL, text TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS daily_cards (
          day TEXT NOT NULL, mode TEXT NOT NULL, payload TEXT NOT NULL,
          PRIMARY KEY(day,mode))''')
        ids = [r['id'] for r in c.execute('SELECT id FROM items')]
        for item_id in ids:
            exists = c.execute('SELECT 1 FROM chunks_v03 WHERE item_id=?', (item_id,)).fetchone()
            if not exists: rebuild(c, item_id)

def get(item_id):
    with connect() as c:
        row = c.execute('SELECT * FROM items WHERE id=?', (item_id,)).fetchone()
        return dict(row) if row else None

def list_items(deleted=False):
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT * FROM items WHERE deleted=? ORDER BY created_at DESC', (int(deleted),))]

def rebuild(c, item_id):
    row = c.execute('SELECT * FROM items WHERE id=?', (item_id,)).fetchone()
    c.execute('DELETE FROM chunks_v03 WHERE item_id=?', (item_id,))
    parts = [(0, row['body'])] + [(r['page'],r['text']) for r in c.execute('SELECT page,text FROM extracted_pages WHERE item_id=?', (item_id,))]
    for page, text in parts:
        for start in range(0, len(text), 680):
            piece = text[start:start+800]
            if piece.strip():
                c.execute('INSERT INTO chunks_v03 VALUES (?,?,?,?,?)', (uuid.uuid4().hex,item_id,page,start,piece))
            if start+800 >= len(text): break

def add(title, space, tags, body, url='', filename='', content=None, local_only=True):
    item_id = uuid.uuid4().hex
    stored = item_id + Path(filename).suffix.lower() if content is not None else ''
    path = FILES / stored if stored else None
    try:
        if path: path.write_bytes(content)
        with connect() as c:
            c.execute('''INSERT INTO items
              (id,title,space,tags,body,url,filename,stored_name,created_at,local_only,sha256)
              VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (item_id,title,space,json.dumps(tags,ensure_ascii=False),body,url,filename,stored,datetime.now().isoformat(timespec='seconds'),int(local_only),hashlib.sha256(content).hexdigest() if content is not None else ''))
            rebuild(c,item_id)
    except Exception:
        if path: path.unlink(missing_ok=True)
        raise
    return item_id

def edit(item_id,title,space,tags,body,local_only):
    with connect() as c:
        c.execute('''UPDATE items SET title=?,space=?,tags=?,body=?,local_only=?,revision=revision+1 WHERE id=?''',
            (title,space,json.dumps(tags,ensure_ascii=False),body,int(local_only),item_id))
        rebuild(c,item_id)

def trash(item_id,deleted=True):
    with connect() as c:
        c.execute('UPDATE items SET deleted=?,revision=revision+1 WHERE id=?',(int(deleted),item_id))

def extract(item_id):
    item = get(item_id)
    if not item or not item['stored_name']: return '无附件；备注可检索'
    path = FILES / item['stored_name']
    pages = []
    try:
        if path.stat().st_size > 50*1024*1024: raise ValueError('文件超过 50 MB')
        if path.suffix.lower() == '.pdf':
            from pypdf import PdfReader
            reader = PdfReader(path)
            if reader.is_encrypted: raise ValueError('加密 PDF，请先提供未加密版本')
            if len(reader.pages)>300: raise ValueError('超过 300 页，请拆分 PDF')
            blank=0
            for n,page in enumerate(reader.pages,1):
                text=(page.extract_text() or '').strip()
                if not text: blank+=1
                if len(text)>100000: raise ValueError('单页文本过长，请拆分文件')
                pages.append((n,text))
            status=f'已提取 {len(pages)-blank}/{len(pages)} 页'
            if blank: status+='；空白或扫描页需 OCR'
        elif path.suffix.lower() in {'.txt','.md'}:
            if path.stat().st_size>2*1024*1024: raise ValueError('文本超过 2 MB，请拆分')
            pages=[(1,path.read_text(encoding='utf-8-sig'))]
            status='已提取文本'
        else:
            status='待支持：图片 OCR / 音视频转录'
    except Exception as exc:
        status='提取失败：' + (str(exc) if isinstance(exc, (ValueError, UnicodeError)) else type(exc).__name__)
    with connect() as c:
        c.execute('DELETE FROM extracted_pages WHERE item_id=?',(item_id,))
        c.executemany('INSERT INTO extracted_pages VALUES (?,?,?)',[(item_id,n,t) for n,t in pages] if not status.startswith('提取失败') else [])
        c.execute('UPDATE items SET extract_status=?,revision=revision+1 WHERE id=?',(status,item_id))
        rebuild(c,item_id)
    return status

def chunks(ids=None):
    with connect() as c:
        rows=c.execute('''SELECT k.id AS chunk_id,k.item_id,k.page,k.offset,k.text,
          i.title,i.space,i.url,i.tags,i.revision,i.local_only
          FROM chunks_v03 k JOIN items i ON i.id=k.item_id WHERE i.deleted=0''').fetchall()
    return [dict(r, search_text=r['title']+'\n'+r['tags']+'\n'+r['text']) for r in rows if ids is None or r['item_id'] in ids]

def validate_sources(sources, consent=False):
    """Reject private, trashed, modified and fabricated stale snapshots before HTTP."""
    if not consent: raise RuntimeError('请先确认允许发送选中的片段。')
    if not sources: raise RuntimeError('没有可发送的片段。')
    verified=[]
    with connect() as c:
        for source in sources:
            row=c.execute('''SELECT k.*,i.title,i.space,i.url,i.local_only,i.deleted,i.revision
               FROM chunks_v03 k JOIN items i ON i.id=k.item_id WHERE k.id=?''',(source.get('chunk_id',''),)).fetchone()
            if not row or row['deleted'] or row['local_only']:
                raise RuntimeError('选材已删除或仅限本地，请重新检索或选材。')
            if row['revision'] != source.get('revision') or row['text'] != source.get('text') or row['title'] != source.get('title'):
                raise RuntimeError('素材已修改，请重新检索或选材。')
            verified.append(dict(source, title=row['title'],text=row['text'],page=row['page']))
    return verified


def duplicates(content):
    digest=hashlib.sha256(content).hexdigest()
    with connect() as c:
        # Backfill old attachment hashes locally, only when checking an upload.
        rows=c.execute("SELECT id,stored_name FROM items WHERE sha256='' AND stored_name<>''").fetchall()
        for row in rows:
            path=FILES/row['stored_name']
            if path.is_file():
                h=hashlib.sha256()
                with path.open('rb') as f:
                    for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
                c.execute('UPDATE items SET sha256=? WHERE id=?',(h.hexdigest(),row['id']))
        return [dict(r) for r in c.execute('SELECT id,title,deleted FROM items WHERE sha256=?',(digest,))]


def permanently_delete(item_id, remove_cards=False):
    """Only trashed items. Stage the original so a DB rollback can restore it."""
    item=get(item_id)
    if not item or not item['deleted']:
        raise ValueError('仅可永久删除回收站内的素材。')
    original=None
    staged=None
    if item['stored_name']:
        original=(FILES/item['stored_name']).resolve()
        if original.parent != FILES.resolve():
            raise ValueError('原件路径异常，已停止删除。')
        if original.is_file():
            staged=FILES/('pending_delete_'+uuid.uuid4().hex)
            original.rename(staged)
    removed_cards=0
    try:
        with connect() as c:
            current=c.execute('SELECT deleted FROM items WHERE id=?',(item_id,)).fetchone()
            if not current or not current['deleted']:raise ValueError('素材状态已变化，已停止删除。')
            if remove_cards:
                for row in c.execute('SELECT day,mode,payload FROM daily_cards').fetchall():
                    payload=json.loads(row['payload'])
                    if any(x.get('item_id')==item_id for x in payload.get('sources',[])):
                        c.execute('DELETE FROM daily_cards WHERE day=? AND mode=?',(row['day'],row['mode']))
                        removed_cards+=1
            c.execute('DELETE FROM chunks_v03 WHERE item_id=?',(item_id,))
            c.execute('DELETE FROM extracted_pages WHERE item_id=?',(item_id,))
            c.execute('DELETE FROM items WHERE id=?',(item_id,))
    except Exception:
        if staged and staged.exists():staged.rename(original)
        raise
    if staged:
        try:staged.unlink()
        except OSError:
            return f'数据库记录已删除，但原件清理失败：{staged.name}。关闭占用程序后手动清理该文件。'
    return f'已永久删除该素材、原件和检索内容；删除关联卡片 {removed_cards} 张。历史备份和导出文件未删除。'
