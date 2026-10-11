import os
import tempfile
import time
import unittest
from pathlib import Path
from datetime import date
from unittest.mock import patch

from happeninki.favourites import Favourites
from happeninki.http import RemoteError
from happeninki.telegram import Telegram
from happeninki.config import load_config
from happeninki.store import Store
from happeninki.models import Event, next_month
from happeninki.__main__ import publish_pending

class Http:
    def __init__(self): self.calls=[]
    def request(self,url,**kwargs):
        self.calls.append((url,kwargs))
        return {'ok':True,'result':{'message_id':123}}

def event():
    return Event(source='tampere',source_id='123',title='Jazz concert',description='Jazz',url='https://example.com/event',
        municipality='Tampere',venue='G Livelab',address='G Livelab',category='music',
        start='2026-10-20T19:00:00+03:00',end='2026-10-20T21:00:00+03:00',dates=[])

class FavouritesTests(unittest.TestCase):
    def test_disabled_or_partial_configuration(self):
        with patch.dict(os.environ,{},clear=True): self.assertIsNone(Favourites.from_environment(Http()))
        with patch.dict(os.environ,{'TELEGRAM_BOT_USERNAME':'HappeninkiBot'},clear=True):
            with self.assertRaises(ValueError): Favourites.from_environment(Http())
        for url in ('http://worker.example','https://user:secret@worker.example','https://worker.example/events'):
            with self.assertRaises(ValueError): Favourites(Http(),url,'secret','HappeninkiBot')

    def test_registration_and_stable_language_links(self):
        http=Http();client=Favourites(http,'https://worker.example','secret','HappeninkiBot')
        links=[client.prepare(event(),{'title':'Jazz','summary':'Summary'},lang)['inline_keyboard'][0][0]['url'] for lang in ['en','ru']]
        self.assertEqual(links[0].split('_')[-1],links[1].split('_')[-1])
        self.assertLessEqual(len(links[0].split('start=')[1]),64)
        self.assertEqual(http.calls[0][1]['headers'],{'Authorization':'Bearer secret'})
        self.assertNotIn('user_id',http.calls[0][1]['body'])
        item=event();item.cancelled=True
        self.assertEqual(client.prepare(item,{'title':'Jazz','summary':'Summary'},'en'),{'inline_keyboard':[]})

    @patch('happeninki.telegram.time.sleep')
    def test_keyboard_preserved_on_photo_fallback_and_edits(self,sleep):
        class RejectPhoto(Http):
            def request(self,url,**kwargs):
                if url.endswith('sendPhoto'):
                    self.calls.append((url,kwargs));raise RemoteError('Telegram',400,description='Bad Request: failed to get HTTP URL content')
                return super().request(url,**kwargs)
        http=RejectPhoto();sender=Telegram(http,'test-token',{'en':'en'})
        keyboard={'inline_keyboard':[[{'text':'Save','url':'https://t.me/HappeninkiBot?start=save_en_abc'}]]}
        sender.publish('en','message',image_url='https://example.com/photo',reply_markup=keyboard)
        self.assertEqual([row[1]['body']['reply_markup'] for row in http.calls],[keyboard,keyboard])
        sender.publish('en','message',123,message_kind='photo',reply_markup=keyboard)
        self.assertEqual(http.calls[-1][1]['body']['reply_markup'],keyboard)

    @patch('happeninki.telegram.time.sleep')
    def test_register_before_send_and_registration_failure_never_sends(self,sleep):
        class Translator:
            def translate(self,item,lang): return {'title':item.title,'summary':'Jazz concert'}
        today=date(2026,10,11)
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'events.db');store.ingest([event()],today,next_month(today))
            http=Http();sender=Telegram(http,'test-token',{'en':'en'},Favourites(http,'https://worker.example','secret','HappeninkiBot'))
            config=load_config()
            self.assertEqual(publish_pending(store,config,Translator(),sender,today,lambda _:None,time.monotonic()+60),(1,0))
            self.assertTrue(http.calls[0][0].endswith('/events'))
            self.assertIn('reply_markup',http.calls[1][1]['body'])
            store.close()
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'events.db');store.ingest([event()],today,next_month(today))
            class Broken(Http):
                def request(self,*args,**kwargs): raise RemoteError('Favourites',503)
            sender=Telegram(Broken(),'test-token',{'en':'en'},Favourites(Broken(),'https://worker.example','secret','HappeninkiBot'))
            self.assertEqual(publish_pending(store,config,Translator(),sender,today,lambda _:None,time.monotonic()+60),(0,1))
            self.assertEqual(store.delivery_holds({'en':'unused'}),[])
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM publications').fetchone()[0],0)
            store.close()
