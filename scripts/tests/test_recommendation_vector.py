"""Vector route contracts; synthetic vectors/review labels are not accuracy data."""
import copy
import hashlib
import unittest

import test_recommendation_engine as contracts
from recommendation_engine import (prepare_retrieval_embeddings, prepare_recommendations,
    review_recommendations, accept_current)
from recommendation_session import source_token, append_scene
from recommendation_retrieval import encoded, MODEL_SHA256


def artifact(bundle):
    items=bundle['embedding_input']['items']
    return {**copy.deepcopy(bundle),'embeddings':{
        'schema_version':1,'complete':True,'total_inputs':len(items),'dimensions':768,
        'model_sha256':MODEL_SHA256,'prefix':'qmd-format-functions-v1',
        'qmd_version':'2.1.0','runtime_version':'3.18.1',
        'dataset_sha256':hashlib.sha256(encoded(bundle['dataset'])).hexdigest(),
        'input_sha256':hashlib.sha256(encoded(bundle['embedding_input'])).hexdigest(),
        'vectors':{item['id']:[1.0]+[0.0]*767 for item in items}}}


class VectorCoreTests(unittest.TestCase):
    setUp=contracts.EngineTests.setUp
    state=contracts.EngineTests.state

    def packet(self, method='vector'):
        session,_=self.state()
        cache=artifact(prepare_retrieval_embeddings(session,self.catalog,self.root))
        request=prepare_recommendations(session,self.catalog,self.root,retrieval_method=method,embedding_artifact=cache)
        reviews={i['id']:contracts.review(i['prepared']['packet']) for i in request['instances']}
        return session,cache,request,reviews

    def test_vector_review_accept_append_loop(self):
        session,cache,request,reviews=self.packet()
        ready=review_recommendations(session,request,reviews,self.catalog,self.root,embedding_artifact=cache)
        proposal=ready['current_batch']['proposals'][0]
        accepted=accept_current(ready,proposal['id'],source_token(ready),ready['batch_sha256'],self.catalog,self.root)
        self.assertEqual(accepted['current_state'],ready['current_state'])
        new=append_scene(accepted,dict(self.project['scenes'][0],id='s2',order=2,text='林读完纸条。'),source_token(accepted))
        with self.assertRaises(ValueError):
            review_recommendations(new,request,reviews,self.catalog,self.root,embedding_artifact=cache)

    def test_bad_similarity_does_not_override_unknown_condition(self):
        session,cache,request,_=self.packet('hybrid')
        reviews={i['id']:contracts.review(i['prepared']['packet'],unknown=[c['fact_id'] for c in i['prepared']['packet']['candidates']]) for i in request['instances']}
        ready=review_recommendations(session,request,reviews,self.catalog,self.root,embedding_artifact=cache)
        self.assertFalse(ready['current_batch']['proposals'])

    def test_changed_cache_cannot_authorize_old_request(self):
        session,cache,request,reviews=self.packet()
        altered=copy.deepcopy(cache)
        q=next(i['id'] for i in altered['embedding_input']['items'] if i['kind']=='query')
        altered['embeddings']['vectors'][q]=[0.,1.]+[0.]*766
        with self.assertRaises(ValueError):
            review_recommendations(session,request,reviews,self.catalog,self.root,embedding_artifact=altered)

    def test_vector_request_requires_artifact_on_review(self):
        session,_,request,reviews=self.packet()
        with self.assertRaises(ValueError):review_recommendations(session,request,reviews,self.catalog,self.root)

    def test_old_bm25_request_shape_preserved(self):
        session,_=self.state()
        request=prepare_recommendations(session,self.catalog,self.root)
        self.assertEqual(set(request),{'schema_version','token','state_sha256','catalog_sha256','top_k','retrieval_method','query','ranking','instances','blocked_actions'})
        self.assertEqual(request['retrieval_method'],'bm25_reviewed_state')

    def test_no_private_source_or_probes_enter_embedding_query(self):
        self.project['scenes'][0]['text'] += '幕后真凶是隐秘角色。'
        session,_=self.state()
        bundle=prepare_retrieval_embeddings(session,self.catalog,self.root)
        query=next(i['text'] for i in bundle['embedding_input']['items'] if i['kind']=='query')
        self.assertEqual(query,'林持有未读纸条。')
        self.assertNotIn('幕后',str(bundle)); self.assertNotIn('core_binding',str(bundle))

    def test_completed_action_still_blocked_with_nearest_vector(self):
        ann=copy.deepcopy(self.annotations)
        ann['registry']['actions'][0].update(origin='observed',status='completed')
        session,_=self.state(ann)
        cache=artifact(prepare_retrieval_embeddings(session,self.catalog,self.root))
        req=prepare_recommendations(session,self.catalog,self.root,retrieval_method='vector',embedding_artifact=cache)
        self.assertEqual(len(req['ranking']),1);self.assertEqual(req['instances'],[])
        ready=review_recommendations(session,req,{},self.catalog,self.root,embedding_artifact=cache)
        self.assertEqual(ready['current_batch']['proposals'],[])

    def test_writer_packet_has_no_vectors_or_retrieval_metadata(self):
        session,cache,request,reviews=self.packet()
        ready=review_recommendations(session,request,reviews,self.catalog,self.root,embedding_artifact=cache)
        packet=ready['current_batch']['writer_packet']
        self.assertEqual(set(packet),{'facts','proposals','instruction'})
        for key in ('vectors','input_sha256','ranking','retrieval_provenance'):
            self.assertNotIn(key,str(packet))


if __name__=='__main__': unittest.main()
