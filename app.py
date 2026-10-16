import html
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
import streamlit as st
import storage as store
from ai_features import settings,render_ask,render_daily
from ui import hero,style,empty

SPACES=['工作与求职','学习与研究','生活与兴趣']
st.set_page_config(page_title='拾集 · 让收藏有回响',page_icon='📚',layout='wide')
store.initialize();style()

def jump(page,item_id=None):
    st.session_state['pending_nav']=page
    st.session_state['detail']=item_id

def flash(text):st.session_state['flash']=text

def tags_of(text):return list(dict.fromkeys(t.strip() for t in re.split('[,，;；\n]',text) if t.strip()))

def kind(item):
    suffix=Path(item['filename']).suffix.lower()
    if suffix=='.pdf':return 'PDF'
    if suffix in {'.png','.jpg','.jpeg','.webp'}:return '图片'
    if suffix in {'.mp4','.mov','.webm'}:return '视频'
    if suffix in {'.txt','.md'}:return '文档'
    return '链接' if item['url'] else '笔记'

if 'pending_nav' in st.session_state:
    st.session_state['nav']=st.session_state.pop('pending_nav')

with st.sidebar:
    st.markdown('## 拾集')
    st.caption('让收藏有回响')
    st.button('＋ 添加素材',type='primary',on_click=jump,args=('添加素材',),use_container_width=True)
    page=st.radio('工作空间',['收藏库','问我的收藏','今日拾得','添加素材','回收站'],key='nav',label_visibility='collapsed')
    st.divider()
    st.caption('LOCAL FIRST · 原件保存在本机')
config=settings()
if st.session_state.get('flash'):st.success(st.session_state.pop('flash'))


def add_page():
    hero('CAPTURE SOMETHING','留住这一刻的灵感','上传原件，贴一段文字，或保存一个链接。以后再慢慢整理。')
    left,right=st.columns([1.7,1],gap='large')
    with right:
        with st.container(border=True):
            st.markdown('#### 支持哪些素材？')
            st.write('文字、PDF、TXT、Markdown、截图和短视频。')
            st.caption('PDF 与文本在本地提取；图片和视频先保存原件，暂未接入 OCR 和转录。单文件不超过 50 MB。')
            st.markdown('#### 默认仅本地')
            st.caption('允许云端的素材也只在你点击 AI 生成后发送选中片段。链接只保存，不自动抓取平台内容。')
    with left:
        generation=st.session_state.get('form_generation',0)
        with st.form('capture'+str(generation),clear_on_submit=False):
            title=st.text_input('标题（选填）',placeholder='给未来的自己留一个好找的名字')
            body=st.text_area('内容或收藏理由',placeholder='这条资料有什么用？你想记住什么？',height=160)
            link=st.text_input('链接或平台分享文案（选填）')
            file=st.file_uploader('拖入文件，或点击选择',type=['pdf','txt','md','png','jpg','jpeg','webp','mp4','mov','webm'])
            a,b=st.columns(2)
            with a:space=st.selectbox('空间',SPACES)
            with b:tags=st.text_input('标签',placeholder='AI，灵感，待阅读')
            local=st.checkbox('仅本地使用',value=True)
            allow_duplicate=st.checkbox('若文件重复，仍保存为独立收藏',value=False)
            submitted=st.form_submit_button('保存到收藏库',type='primary')
        if submitted:
            try:
                if not(body.strip() or link.strip() or file):raise ValueError('请添加文字、链接或文件。')
                if file and file.size>50*1024*1024:raise ValueError('文件超过 50 MB。')
                match=re.search(r'https?://[^\s<>"\']+',link)
                url=match.group(0).rstrip('。，；！？、）)]}') if match else ''
                if link.strip() and (not url or not urlsplit(url).hostname):raise ValueError('没有找到有效网址，请检查分享文案。')
                raw=file.getvalue() if file else None
                duplicates=store.duplicates(raw) if raw is not None else []
                if duplicates and not allow_duplicate:
                    names='、'.join(i['title']+('（回收站）' if i['deleted'] else '') for i in duplicates[:3])
                    st.warning('这个文件已经收藏过：'+names)
                    st.caption('可以返回查看原收藏，或勾选“仍保存为独立收藏”后再保存。')
                    return
                content=body.strip()+('\n\n分享原文：\n'+link if link.strip() else '')
                item_id=store.add(title.strip() or (file.name if file else content[:40]),space,tags_of(tags),content,url,file.name if file else '',raw,local)
                with st.spinner('已保存原件，正在本地整理文字……'):
                    status=store.extract(item_id) if file else '文字已可检索'
                flash('已收藏 · '+status)
                st.session_state['form_generation']=generation+1
                jump('收藏库',item_id);st.rerun()
            except Exception as exc:st.error(f'没有保存成功：{type(exc).__name__}: {exc}')


def detail(item):
    item_id=item['id']
    st.button('← 返回收藏库',on_click=jump,args=('收藏库',))
    hero(kind(item),item['title'],item['space']+' · '+item['created_at'][:10])
    left,right=st.columns([1.65,1],gap='large')
    with right:
        with st.container(border=True):
            st.markdown('#### 素材信息')
            st.write('🔒 仅本地' if item['local_only'] else '☁ 允许用于云端生成')
            st.caption('文件状态：'+(item['extract_status'] if item['stored_name'] else '文字已可检索'))
            st.caption('标签：'+' / '.join(json.loads(item['tags'])))
            if item['url'] and urlsplit(item['url']).scheme in {'http','https'}:st.link_button('打开原始来源 ↗',item['url'])
            if item['stored_name']:
                path=store.FILES/item['stored_name']
                if path.is_file():
                    st.download_button('下载原件',path.read_bytes(),file_name=item['filename'],key='dl'+item_id)
                    if st.button('重新提取正文' if item['extract_status'].startswith('已提取') else '提取文件正文',key='extract'+item_id):
                        with st.spinner('仅在本地提取……'):status=store.extract(item_id)
                        flash(status);st.rerun()
                else:st.warning('原件文件缺失。')
        with st.expander('编辑信息'):
            with st.form('edit'+item_id):
                title=st.text_input('标题',item['title'])
                opts=list(dict.fromkeys(SPACES+[item['space']]))
                space=st.selectbox('空间',opts,index=opts.index(item['space']))
                tags=st.text_input('标签','，'.join(json.loads(item['tags'])))
                body=st.text_area('内容 / 备注',item['body'],height=180)
                local=st.checkbox('仅本地使用',bool(item['local_only']))
                submitted=st.form_submit_button('保存修改',type='primary')
            if submitted:
                if not title.strip():st.error('标题不能为空。')
                else:
                    store.edit(item_id,title.strip(),space,tags_of(tags),body,local)
                    flash('已更新。后续检索使用新内容。');st.rerun()
        with st.expander('移入回收站'):
            st.caption('从检索与每日选材中移除，原件保留，可随时恢复。')
            if st.button('确认移入回收站',key='trash'+item_id):
                store.trash(item_id);jump('收藏库');flash('已移入回收站，可从左侧恢复。');st.rerun()
    with left:
        with st.container(border=True):
            st.markdown('#### 收藏内容')
            if item['body']:st.text(item['body'])
            else:st.caption('没有备注，可以在右侧补充收藏理由。')
            if item['stored_name']:
                path=store.FILES/item['stored_name']
                if path.is_file():
                    suffix=path.suffix.lower()
                    if suffix in {'.jpg','.jpeg','.png','.webp'}:
                        try:st.image(str(path))
                        except Exception:st.caption('预览失败，可下载原件查看。')
                    elif suffix in {'.mp4','.mov','.webm'}:st.video(path.read_bytes())
        with store.connect() as c:pages=c.execute('SELECT page,text FROM extracted_pages WHERE item_id=? ORDER BY page',(item_id,)).fetchall()
        if pages:
            with st.container(border=True):
                st.markdown('#### 提取正文')
                page_no=st.selectbox('查看文件页 / 文本段',[p['page'] for p in pages],key='page'+item_id)
                st.text(next(p['text'] or '该页没有提取到文字，可能需要 OCR。' for p in pages if p['page']==page_no))
                st.caption('PDF 页码按文件顺序计数，可能与纸面印刷页码不同。')


def collection():
    selected=st.session_state.get('detail')
    if selected:
        item=store.get(selected)
        if item and not item['deleted']:detail(item);return
        st.session_state['detail']=None
    items=store.list_items()
    hero('YOUR PERSONAL COLLECTION','每一次收藏，都值得再发现','把工作资料、学习笔记和生活灵感，放在一个找得到的地方。')
    a,b,c=st.columns(3)
    a.metric('已收藏',len(items));b.metric('仅本地',sum(i['local_only'] for i in items))
    with store.connect() as conn:count=conn.execute('SELECT COUNT(*) FROM daily_cards').fetchone()[0]
    c.metric('收获卡片',count)
    search=st.text_input('搜索收藏',placeholder='搜索标题、备注、标签、文件名或提取正文',label_visibility='collapsed')
    a,b,c=st.columns([1,1,1])
    with a:space=st.selectbox('空间',['全部空间']+SPACES)
    with b:type_filter=st.selectbox('类型',['全部类型','笔记','链接','PDF','文档','图片','视频'])
    with c:privacy=st.selectbox('使用范围',['全部','仅本地','允许云端'])
    with st.expander('更多筛选'):
        tags=st.multiselect('标签',sorted({t for i in items for t in json.loads(i['tags'])}))
        order=st.radio('排序',['最近收藏','最早收藏','标题'],horizontal=True)
    query=search.strip().casefold()
    matches=set()
    if query:
        with store.connect() as conn:matches={r['item_id'] for r in conn.execute('SELECT item_id,text FROM extracted_pages') if query in r['text'].casefold()}
    visible=[i for i in items if (space=='全部空间' or i['space']==space) and (type_filter=='全部类型' or kind(i)==type_filter) and (privacy=='全部' or bool(i['local_only'])==(privacy=='仅本地')) and set(tags).issubset(json.loads(i['tags'])) and (not query or i['id'] in matches or query in (i['title']+i['body']+i['tags']+i['filename']).casefold())]
    if order=='最早收藏':visible.reverse()
    if order=='标题':visible.sort(key=lambda i:i['title'])
    st.caption(f'找到 {len(visible)} 条收藏')
    if not visible:
        empty('这里还没有匹配的素材。添加第一条收藏，或调整筛选条件。');return
    number=st.selectbox('页码',list(range(1,(len(visible)+7)//8+1)))
    columns=st.columns(2,gap='medium')
    for n,item in enumerate(visible[(number-1)*8:number*8]):
        with columns[n%2]:
            with st.container(border=True):
                labels=[kind(item),item['space'],'仅本地' if item['local_only'] else '允许云端']
                st.markdown(''.join('<span class="pill">'+html.escape(x)+'</span>' for x in labels),unsafe_allow_html=True)
                st.markdown('<div class="card-title">'+html.escape(item['title'])+'</div>',unsafe_allow_html=True)
                snippet=item['body'][:110] or item['filename'] or '打开查看素材'
                st.markdown('<div class="excerpt">'+html.escape(snippet)+'</div>',unsafe_allow_html=True)
                st.caption(item['created_at'][:10]+' · '+(item['extract_status'] if item['stored_name'] else '文字已可检索'))
                st.button('查看详情 →',key='open'+item['id'],on_click=jump,args=('收藏库',item['id']))


def trash_page():
    hero('RECYCLE BIN','回收站','移除的素材不会参与新的检索和生成，原件仍保留在本机。')
    items=store.list_items(True)
    if not items:empty('回收站为空。')
    for item in items:
        with st.container(border=True):
            a,b=st.columns([4,1])
            a.write(item['title']);a.caption(item['space']+' · '+item['created_at'][:10])
            if b.button('恢复',key='restore'+item['id']):
                store.trash(item['id'],False);flash('已恢复到收藏库。');st.rerun()
            with st.expander('永久删除…'):
                st.warning('永久删除会移除本条素材、原件、提取文字和检索分块，不能从回收站恢复。')
                st.caption('历史备份、导出的笔记和其他重复收藏不在此次删除范围内。')
                remove_cards=st.checkbox('同时删除引用该素材的历史卡片（整张删除）',key='remove_cards'+item['id'])
                confirmed=st.text_input('输入 DELETE 确认',key='delete_confirm'+item['id'])
                if st.button('永久删除此素材',key='delete'+item['id'],disabled=confirmed!='DELETE'):
                    try:
                        message=store.permanently_delete(item['id'],remove_cards)
                        for cached in ['a4','s4']:
                            st.session_state.pop(cached,None)
                        flash(message);st.rerun()
                    except (OSError,ValueError,store.sqlite3.Error) as exc:
                        st.error('删除未完成：'+str(exc))


if page=='添加素材':add_page()
elif page=='收藏库':collection()
elif page=='问我的收藏':render_ask(config)
elif page=='今日拾得':render_daily(config)
else:trash_page()
