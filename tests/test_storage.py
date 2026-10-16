import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import storage as s

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        self.patches=[patch.object(s,'DB',root/'shiji.db'),patch.object(s,'DATA',root),patch.object(s,'FILES',root/'files')]
        for p in self.patches:p.start()
        s.initialize()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def add(self,local=False):return s.add('RAG','学习与研究',['AI'],'retrieval evidence and citation',local_only=local)
    def test_migration_preserves_old_rows_and_history(self):
        with s.connect() as c:
            c.execute('DROP TABLE items')
            c.execute('CREATE TABLE items (id TEXT PRIMARY KEY,title TEXT,space TEXT,tags TEXT,body TEXT,url TEXT,filename TEXT,stored_name TEXT,created_at TEXT)')
            c.execute("INSERT INTO items VALUES ('old','title','space','[]','body','','','','2026')")
            c.execute("INSERT INTO daily_cards VALUES ('2026','学习','{}')")
        s.initialize();s.initialize()
        self.assertEqual(s.get('old')['body'],'body')
        self.assertEqual(s.get('old')['local_only'],1)
        with s.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM daily_cards').fetchone()[0],1)
    def test_private_blocked_at_network_boundary(self):
        import ai_features as ai
        self.add(True)
        with patch.object(ai,'urlopen') as http:
            with self.assertRaises(RuntimeError):ai.generate('fake','fake','q',s.chunks(),True)
            http.assert_not_called()
    def test_permission_change_after_retrieval(self):
        i=self.add();sources=s.chunks()
        s.edit(i,'RAG','学习与研究',[],'secret',True)
        with self.assertRaises(RuntimeError):s.validate_sources(sources,True)
    def test_edit_invalidates_and_reindexes(self):
        i=self.add();old=s.chunks()
        s.edit(i,'New','学习与研究',[],'replacement',False)
        with self.assertRaises(RuntimeError):s.validate_sources(old,True)
        self.assertEqual(s.chunks()[0]['text'],'replacement')
    def test_trash_restore(self):
        i=self.add();old=s.chunks();s.trash(i)
        self.assertEqual(s.chunks(),[])
        with self.assertRaises(RuntimeError):s.validate_sources(old,True)
        s.trash(i,False);self.assertTrue(s.chunks())
    def test_consent_required(self):
        self.add()
        with self.assertRaises(RuntimeError):s.validate_sources(s.chunks(),False)
    def test_allowed_request_and_no_key_in_result(self):
        import ai_features as ai
        self.add()
        class Response(io.BytesIO):
            pass
        response=Response(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'answer [S1]'}}]}).encode())
        with patch.object(ai,'urlopen',return_value=response) as http:
            result=ai.generate('test-secret','test-model','question',s.chunks(),True)
            payload=json.loads(http.call_args.args[0].data)
            self.assertIn('retrieval evidence',payload['messages'][1]['content'])
        self.assertNotIn('test-secret',json.dumps(result))
    def test_length_error(self):
        import ai_features as ai
        self.add()
        response=io.BytesIO(json.dumps({'choices':[{'finish_reason':'length','message':{'content':None}}]}).encode())
        with patch.object(ai,'urlopen',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'额度耗尽'):ai.generate('fake','fake','q',s.chunks(),True)
    def test_pdf_pages_and_empty_pdf(self):
        # Build a tiny text PDF using pypdf; no extra test dependency.
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        w=PdfWriter()
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        for phrase in ['Alpha retrieval','Beta grounding']:
            page=w.add_blank_page(300,300)
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
            stream=DecodedStreamObject();stream.set_data(f'BT /F1 12 Tf 10 200 Td ({phrase}) Tj ET'.encode())
            page[NameObject('/Contents')]=w._add_object(stream)
        out=io.BytesIO();w.write(out)
        i=s.add('PDF','学习与研究',[],'',filename='test.pdf',content=out.getvalue())
        self.assertIn('2/2',s.extract(i))
        sources=s.chunks([i]);self.assertEqual({x['page'] for x in sources},{1,2})
        self.assertTrue(any('Beta grounding' in x['text'] and x['page']==2 for x in sources))
        blank=PdfWriter();blank.add_blank_page(300,300);out=io.BytesIO();blank.write(out)
        j=s.add('scan','学习与研究',[],'',filename='blank.pdf',content=out.getvalue())
        self.assertIn('OCR',s.extract(j))
    def test_duplicate_file_and_trash(self):
        i=s.add('file','学习与研究',[],'',filename='a.txt',content=b'hello')
        self.assertEqual(s.duplicates(b'hello')[0]['id'],i)
        self.assertEqual(s.duplicates(b'world'),[])
        s.trash(i)
        self.assertEqual(s.duplicates(b'hello')[0]['deleted'],1)
    def test_old_hash_backfill(self):
        i=s.add('file','学习与研究',[],'',filename='a.txt',content=b'hello')
        with s.connect() as c:c.execute("UPDATE items SET sha256='' WHERE id=?",(i,))
        self.assertEqual(s.duplicates(b'hello')[0]['id'],i)
    def test_permanent_delete_and_cards(self):
        i=s.add('file','学习与研究',[],'RAG',filename='a.txt',content=b'hello',local_only=False)
        s.extract(i)
        original=s.FILES/s.get(i)['stored_name']
        with s.connect() as c:c.execute('INSERT INTO daily_cards VALUES (?,?,?)',('2026','learning',json.dumps({'sources':[{'item_id':i}]})))
        with self.assertRaises(ValueError):s.permanently_delete(i)
        self.assertTrue(original.exists())
        s.trash(i);s.permanently_delete(i,True)
        self.assertIsNone(s.get(i));self.assertFalse(original.exists())
        with s.connect() as c:
            for table in ['extracted_pages','chunks_v03','daily_cards']:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
    def test_delete_keeps_cards_unless_selected(self):
        i=self.add()
        with s.connect() as c:c.execute('INSERT INTO daily_cards VALUES (?,?,?)',('2026','learning',json.dumps({'sources':[{'item_id':i}]})))
        s.trash(i);s.permanently_delete(i,False)
        with s.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM daily_cards').fetchone()[0],1)
    def test_single_pdf_can_return_more_than_two_chunks(self):
        import ai_features as ai
        i=s.add('pdf','学习与研究',[],'RAG evaluation '*500,local_only=False)
        results=ai.retrieve('RAG',s.chunks([i]),limit=8,per_item_limit=8)
        self.assertGreater(len(results),2)
    def test_restart_persists(self):
        i=self.add();s.initialize();self.assertEqual(s.get(i)['title'],'RAG')

if __name__=='__main__':unittest.main()
