"""Read-only source fixtures prove additions, changes, removals and absent-service reporting."""
import unittest,tempfile,pathlib,subprocess,json,shutil,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
class DiscoveryTests(unittest.TestCase):
 def test_fixture_route_lifecycle(self):
  # Run a copy of the generator so tests never modify central production contracts.
  with tempfile.TemporaryDirectory(prefix='asodya-doc-test-') as tmp:
   root=pathlib.Path(tmp);(root/'tools').mkdir();(root/'src/core').mkdir(parents=True);(root/'src/presentation/assets').mkdir(parents=True);shutil.copy(ROOT/'tools/generate_docs.py',root/'tools/generate_docs.py')
   shutil.copy(ROOT/'Cargo.toml',root/'Cargo.toml')
   for f in ['defaults.json','apps.json']:shutil.copy(ROOT/'src/core'/f,root/'src/core'/f)
   shutil.copy(ROOT/'src/presentation/assets/gateway_contracts.json',root/'src/presentation/assets/gateway_contracts.json');repo=root/'domain_api';repo.mkdir();route=repo/'routes.py'
   def generate():
    subprocess.run(['python3',str(root/'tools/generate_docs.py'),'--workspace',str(root)],check=True,capture_output=True);return json.loads((root/'src/presentation/assets/openapi.json').read_text())
   annotations=root/'annotations_api/lib/presentation';annotations.mkdir(parents=True);(annotations/'mod.rs').write_text('pub fn router() { Router::new().route("/health", get(health)).route("/instant/{code}", get(read).put(create)) }')
   cert=root/'certifications_api/lib/presentation';cert.mkdir(parents=True);(cert/'mod.rs').write_text('pub fn router() { Router::new().route("/ready", get(ready)).route("/studies/prepared", post(prepared)) }')
   route.write_text('from fastapi import APIRouter\nfrom pydantic import BaseModel\nclass FixtureRequest(BaseModel):\n title: str\nr=APIRouter(prefix="/fixture")\n@r.get("/one")\ndef one(q: str):\n return {"answer":q}\n@r.post("/typed")\ndef typed(payload: FixtureRequest):\n return {"ok": True}\n');v=generate();self.assertEqual(v['paths']['/apps/annotations/v1/instant/{code}']['put']['security'],[]);self.assertIn('/apps/annotations/v1/health',v['paths']);self.assertIn('/apps/certifications/v1/studies/prepared',v['paths']);self.assertIn('/apps/domain/v1/fixture/one',v['paths']);self.assertIn('requestBody',v['paths']['/apps/domain/v1/fixture/typed']['post'])
   offline=root/'domain-offline';repo.rename(offline);cached=generate();self.assertIn('/apps/domain/v1/fixture/one',cached['paths']);offline.rename(repo)
   route.write_text(route.read_text().replace('/one','/two'));v=generate();self.assertNotIn('/apps/domain/v1/fixture/one',v['paths']);self.assertIn('/apps/domain/v1/fixture/two',v['paths'])
   route.unlink();v=generate();self.assertNotIn('/apps/domain/v1/fixture/two',v['paths'])

class CortexRustDiscoveryTests(unittest.TestCase):
 def test_cortex_rust_route_and_model_lifecycle(self):
  with tempfile.TemporaryDirectory(prefix='cortex-doc-test-') as tmp:
   root=pathlib.Path(tmp);(root/'tools').mkdir();(root/'src/core').mkdir(parents=True);(root/'src/presentation/assets').mkdir(parents=True)
   shutil.copy(ROOT/'tools/generate_docs.py',root/'tools/generate_docs.py');shutil.copy(ROOT/'Cargo.toml',root/'Cargo.toml')
   for name in ['defaults.json','apps.json']:shutil.copy(ROOT/'src/core'/name,root/'src/core'/name)
   shutil.copy(ROOT/'src/presentation/assets/gateway_contracts.json',root/'src/presentation/assets/gateway_contracts.json')
   repo=root/'cortex_api';(repo/'src/presentation').mkdir(parents=True);(repo/'src/domain/models').mkdir(parents=True)
   (repo/'src/main.rs').write_text('fn main() { cortex_api::presentation::chat_inputs::router(state); }')
   route=repo/'src/presentation/chat_inputs.rs';models=repo/'src/domain/models/chat.rs'
   # The worker is a separate LAN binary, not part of the public Cortex router.
   (repo/'src/presentation/file_worker.rs').write_text('fn router() { Router::new().route("/worker-only", post(job)) }')
   models.write_text('''#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NewChat {
 pub app_id: String,
 #[serde(rename = "type")]
 pub kind: PersonaType,
 #[serde(default)]
 pub stream: bool,
 pub note: Option<String>,
}
#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PersonaType { Person, Bot, }
''')
   route.write_text('''pub fn router() { Router::new().route("/chats", post(create)).route("/models", get(|| async { value() })) }
async fn create(Json(body): Json<NewChat>) -> Response { response() }
''')
   def generate():
    subprocess.run(['python3',str(root/'tools/generate_docs.py'),'--workspace',str(root)],check=True,capture_output=True)
    return json.loads((root/'src/presentation/assets/openapi.json').read_text())
   doc=generate();op=doc['paths']['/apps/cortex/v1/chats']['post'];ref=op['requestBody']['content']['application/json']['schema']['$ref'];model=doc['components']['schemas'][ref.rsplit('/',1)[-1]]
   self.assertEqual(model['required'],['app_id','type']);self.assertFalse(model['additionalProperties']);self.assertIn('stream',model['properties']);self.assertNotIn('kind',model['properties'])
   enum=doc['components']['schemas'][model['properties']['type']['$ref'].rsplit('/',1)[-1]];self.assertEqual(enum['enum'],['person','bot'])
   self.assertIn('/apps/cortex/v1/models',doc['paths']);self.assertNotIn('/apps/cortex/v1/worker-only',doc['paths']);self.assertIn('x-discovery-gaps',op)
   models.write_text(models.read_text().replace(' pub app_id: String,',' pub app_id: String,\n pub question: String,'))
   route.write_text(route.read_text().replace('"/chats"','"/questions"'))
   doc=generate();self.assertNotIn('/apps/cortex/v1/chats',doc['paths']);self.assertIn('/apps/cortex/v1/questions',doc['paths']);self.assertIn('question',doc['components']['schemas'][ref.rsplit('/',1)[-1]]['required'])
   offline=root/'cortex-offline';repo.rename(offline);cached=generate();self.assertIn('/apps/cortex/v1/questions',cached['paths']);offline.rename(repo)
   route.unlink();doc=generate();self.assertNotIn('/apps/cortex/v1/questions',doc['paths'])

 def test_cortex_app_router_composition_and_remote_sse(self):
  with tempfile.TemporaryDirectory(prefix='cortex-app-router-') as tmp:
   root=pathlib.Path(tmp);(root/'tools').mkdir();(root/'src/core').mkdir(parents=True);(root/'src/presentation/assets').mkdir(parents=True)
   shutil.copy(ROOT/'tools/generate_docs.py',root/'tools/generate_docs.py');shutil.copy(ROOT/'Cargo.toml',root/'Cargo.toml')
   for name in ['defaults.json','apps.json']:shutil.copy(ROOT/'src/core'/name,root/'src/core'/name)
   shutil.copy(ROOT/'src/presentation/assets/gateway_contracts.json',root/'src/presentation/assets/gateway_contracts.json')
   repo=root/'cortex_api';(repo/'src/presentation').mkdir(parents=True);(repo/'src/domain/models').mkdir(parents=True)
   (repo/'src/main.rs').write_text('fn main() { cortex_api::presentation::app_router(services); }')
   (repo/'src/presentation/mod.rs').write_text('pub fn app_router(s: S) -> Router { Router::new().merge(remote_cli::routes(s.remote)) }')
   (repo/'src/presentation/remote_cli.rs').write_text('pub fn routes(s: S) -> Router { Router::new().route("/remote/sessions/{id}/commands", get(cli_commands_sse)) }')
   subprocess.run(['python3',str(root/'tools/generate_docs.py'),'--workspace',str(root)],check=True,capture_output=True)
   doc=json.loads((root/'src/presentation/assets/openapi.json').read_text())
   op=doc['paths']['/apps/cortex/v1/remote/sessions/{id}/commands']['get']
   self.assertIn('text/event-stream',op['responses']['200']['content'])
   self.assertNotIn('x-discovery-gaps',op)

 def test_certifications_contracts_and_portable_discovery(self):
  with tempfile.TemporaryDirectory(prefix='cert-doc-test-') as tmp:
   root=pathlib.Path(tmp);(root/'tools').mkdir();(root/'src/core').mkdir(parents=True);(root/'src/presentation/assets').mkdir(parents=True)
   shutil.copy(ROOT/'tools/generate_docs.py',root/'tools/generate_docs.py');shutil.copy(ROOT/'Cargo.toml',root/'Cargo.toml')
   for name in ['defaults.json','apps.json']:shutil.copy(ROOT/'src/core'/name,root/'src/core'/name)
   shutil.copy(ROOT/'src/presentation/assets/gateway_contracts.json',root/'src/presentation/assets/gateway_contracts.json')
   repo=root/'certifications_api';(repo/'lib/presentation').mkdir(parents=True);(repo/'lib/domain').mkdir(parents=True)
   (repo/'lib/presentation/mod.rs').write_text('''pub fn routes() {
 Router::new()
  .route("/studies", get(list_studies).post(create_study))
  .route("/studies/prepared", post(create_prepared))
  .route("/studies/{study_id}", get(study_detail))
  .route("/studies/{study_id}/sources", post(add_source))
  .route("/quizzes/{quiz_id}/statistics", get(get_quiz_statistics))
  .route("/me/quizzes/{quiz_id}/statistics", get(get_my_quiz_statistics))
  .route("/me/quizzes/{quiz_id}/summary", get(get_my_quiz_summary))
  .route("/attempts", get(list_my_attempts))
  .route("/studies/{study_id}/questions/{question_id}/visuals", post(upload_visual))
  .route("/attempts/{attempt_id}/question_versions/{question_version_id}/visuals/{visual_id}", get(get_attempt_question_visual))
}''')
   (repo/'lib/domain/visuals.rs').write_text('''pub struct QuestionVisual {
    pub id: String,
    #[serde(skip_serializing)]
    pub fsm_ref: String,
    pub mime_type: String,
    pub created_at: i64,
}
pub struct UploadVisualReceipt {
    pub id: String,
    pub mime_type: String,
    pub created_at: i64,
    pub prepared_question_version_id: String,
    pub result_question_version_id: String,
    pub result_quiz_version_id: String,
}
pub struct AttemptVisualReference {
    pub id: String,
    pub mime_type: String,
    pub created_at: i64,
}
pub struct TakingQuestion {
    pub question_id: String,
    pub question_version_id: String,
    pub language: String,
    pub origin: String,
    pub prompt: String,
    pub alternatives: Value,
    pub selected_option_id: Option<String>,
    pub visuals: Vec<AttemptVisualReference>,
}
pub struct ReviewedQuestion {
    pub question_id: String,
    pub question_version_id: String,
    pub language: String,
    pub origin: String,
    pub prompt: String,
    pub alternatives: Value,
    pub selected_option_id: Option<String>,
    pub correct_id: String,
    pub is_correct: bool,
    pub explanation: String,
    pub citation_ref: String,
    pub visuals: Vec<AttemptVisualReference>,
}
''')
   (repo/'lib/domain/studies.rs').write_text('''pub struct PreparedStudyConfig {
    pub language: String,
    pub count: i64,
}
pub struct UploadSourceBody {
    pub kind: Option<String>,
    pub filename: String,
    pub mime_type: String,
    pub content_text: Option<String>,
    pub external_ref: Option<String>,
    pub fsm_ref: Option<String>,
    pub size_bytes: Option<i64>,
    pub is_restricted: bool,
}
pub struct PreparedStudyInput {
    pub title: String,
    pub description: String,
    pub config: Option<PreparedStudyConfig>,
}
pub struct StudyDetail {
    pub study: StudySummary,
    pub sources: Vec<SourceSummary>,
    pub quota: QuotaMeter,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub config: Option<PreparedStudyConfig>,
}
pub struct AvailableStudyTag {
    pub slug: String,
    pub label: String,
}
pub struct StudyHistoryPage {
    pub items: Vec<StudySummary>,
    pub total: i64,
    pub limit: i64,
    pub offset: i64,
    pub available_tags: Vec<AvailableStudyTag>,
}
pub struct PublicQuizStats {
    pub quiz_id: String,
    pub completed_attempt_count: i64,
}
pub struct OwnerQuizSummary {
    pub quiz_id: String,
    pub active_version_id: Option<String>,
    pub title: Option<String>,
    pub question_count: Option<i64>,
    pub subject: Option<String>,
}
pub struct AttemptHistoryItem {
    pub id: String,
    pub status: String,
}
pub struct AttemptHistoryPage {
    pub items: Vec<AttemptHistoryItem>,
    pub total: i64,
    pub limit: i64,
    pub offset: i64,
}
''')
   subprocess.run(['python3',str(root/'tools/generate_docs.py'),'--workspace',str(root)],check=True,capture_output=True)
   doc=json.loads((root/'src/presentation/assets/openapi.json').read_text())
   schemas=doc['components']['schemas']
   # StudyDetail top-level config
   self.assertIn('Certifications_StudyDetail',schemas)
   self.assertIn('config',schemas['Certifications_StudyDetail']['properties'])
   self.assertIn('study',schemas['Certifications_StudyDetail']['properties'])
   self.assertIn('sources',schemas['Certifications_StudyDetail']['properties'])
   self.assertIn('quota',schemas['Certifications_StudyDetail']['properties'])
   # PreparedStudyInput and PreparedStudyConfig
   self.assertIn('Certifications_PreparedStudyConfig',schemas)
   self.assertIn('language',schemas['Certifications_PreparedStudyConfig']['properties'])
   self.assertIn('count',schemas['Certifications_PreparedStudyConfig']['properties'])
   self.assertIn('config',schemas['Certifications_PreparedStudyInput']['properties'])
   # StudyHistoryPage and AvailableStudyTag
   self.assertIn('Certifications_StudyHistoryPage',schemas)
   self.assertIn('Certifications_AvailableStudyTag',schemas)
   # OwnerQuizSummary and AttemptHistoryPage
   self.assertIn('Certifications_OwnerQuizSummary',schemas)
   self.assertIn('quiz_id',schemas['Certifications_OwnerQuizSummary']['properties'])
   self.assertIn('active_version_id',schemas['Certifications_OwnerQuizSummary']['properties'])
   self.assertIn('question_count',schemas['Certifications_OwnerQuizSummary']['properties'])
   self.assertIn('Certifications_AttemptHistoryPage',schemas)
   self.assertIn('items',schemas['Certifications_AttemptHistoryPage']['properties'])
   self.assertIn('total',schemas['Certifications_AttemptHistoryPage']['properties'])
   # /me/quizzes/{quiz_id}/summary is session-protected
   summary_op=doc['paths']['/apps/certifications/v1/me/quizzes/{quiz_id}/summary']['get']
   self.assertEqual(summary_op['x-access-level'],'session')
   self.assertEqual(summary_op['security'],[{'SessionCookie':[]}])
   self.assertEqual(summary_op['responses']['200']['content']['application/json']['schema']['$ref'],'#/components/schemas/Certifications_OwnerQuizSummary')
   # /attempts GET pagination and filter query parameters
   attempts_op=doc['paths']['/apps/certifications/v1/attempts']['get']
   attempts_params=[p['name'] for p in attempts_op['parameters']]
   for expected_param in ('limit','offset','q','started_from','started_to','quiz_id','tag','status'):
    self.assertIn(expected_param,attempts_params)
   self.assertEqual(attempts_op['x-access-level'],'session')
   self.assertEqual(attempts_op['responses']['200']['content']['application/json']['schema']['$ref'],'#/components/schemas/Certifications_AttemptHistoryPage')
   # /studies GET pagination query parameters
   studies_op=doc['paths']['/apps/certifications/v1/studies']['get']
   param_names=[p['name'] for p in studies_op['parameters']]
   for expected_param in ('limit','offset','q','created_from','created_to','status','quiz_id','tag'):
    self.assertIn(expected_param,param_names)
   self.assertEqual(studies_op['responses']['200']['content']['application/json']['schema']['$ref'],'#/components/schemas/Certifications_StudyHistoryPage')
   # /studies/{study_id}/sources POST dual request formats: multipart/form-data and application/json
   sources_op=doc['paths']['/apps/certifications/v1/studies/{study_id}/sources']['post']
   sources_content=sources_op['requestBody']['content']
   self.assertIn('multipart/form-data',sources_content)
   self.assertIn('application/json',sources_content)
   mp_schema=sources_content['multipart/form-data']['schema']
   self.assertEqual(mp_schema['required'],['file'])
   self.assertFalse(mp_schema.get('additionalProperties',True))
   self.assertIn('file',mp_schema['properties'])
   self.assertIn('filename',mp_schema['properties'])
   self.assertIn('mime_type',mp_schema['properties'])
   for prohibited in ('fsm_ref','is_restricted','kind','content_text','external_ref','size_bytes','selection_spec','selection_kind','owner_id','user_id','access_level','is_admin','role'):
    self.assertNotIn(prohibited,mp_schema['properties'])
   json_ref=sources_content['application/json']['schema']['$ref']
   self.assertEqual(json_ref,'#/components/schemas/Certifications_UploadSourceBody')
   self.assertIn('Certifications_UploadSourceBody',schemas)
   body_schema=schemas['Certifications_UploadSourceBody']
   self.assertEqual(body_schema['required'],['filename'])
   self.assertFalse(body_schema.get('additionalProperties',True))
   self.assertIn('kind',body_schema['properties'])
   self.assertNotIn('enum',body_schema['properties']['kind'])
   self.assertIn('reference',body_schema['properties']['kind']['description'].lower())
   self.assertIn('storage artifact',body_schema['properties']['fsm_ref']['description'].lower())
   self.assertIn('content_text',body_schema['properties'])
   self.assertIn('fsm_ref',body_schema['properties'])
   self.assertIn('external_ref',body_schema['properties'])
   self.assertIn('size_bytes',body_schema['properties'])
   self.assertIn('is_restricted',body_schema['properties'])
   # /me/quizzes/{quiz_id}/statistics is session-protected
   my_stats=doc['paths']['/apps/certifications/v1/me/quizzes/{quiz_id}/statistics']['get']
   self.assertEqual(my_stats['x-access-level'],'session')
   self.assertEqual(my_stats['security'],[{'SessionCookie':[]}])
   # /quizzes/{quiz_id}/statistics is public
   pub_stats=doc['paths']['/apps/certifications/v1/quizzes/{quiz_id}/statistics']['get']
   self.assertEqual(pub_stats['x-access-level'],'public')
   self.assertEqual(pub_stats['security'],[])
   # Visual authoring and attempt visual models
   self.assertIn('Certifications_StudyDetail',schemas)
   self.assertIn('config',schemas['Certifications_StudyDetail']['properties'])
   self.assertNotIn('config',schemas['Certifications_StudyDetail'].get('required',[]))
   self.assertIn('Certifications_UploadVisualReceipt',schemas)
   self.assertEqual(schemas['Certifications_UploadVisualReceipt']['required'],['id','mime_type','created_at','prepared_question_version_id','result_question_version_id','result_quiz_version_id'])
   self.assertIn('Certifications_QuestionVisual',schemas)
   self.assertNotIn('fsm_ref',schemas['Certifications_QuestionVisual']['properties'])
   self.assertNotIn('fsm_ref',schemas['Certifications_QuestionVisual'].get('required',[]))
   self.assertEqual(schemas['Certifications_QuestionVisual']['required'],['id','mime_type','created_at'])
   self.assertIn('Certifications_AttemptVisualReference',schemas)
   self.assertEqual(schemas['Certifications_AttemptVisualReference']['required'],['id','mime_type','created_at'])
   self.assertEqual(schemas['Certifications_TakingQuestion']['properties']['visuals']['items']['$ref'],'#/components/schemas/Certifications_AttemptVisualReference')
   self.assertIn('visuals',schemas['Certifications_TakingQuestion']['required'])
   self.assertEqual(schemas['Certifications_ReviewedQuestion']['properties']['visuals']['items']['$ref'],'#/components/schemas/Certifications_AttemptVisualReference')
   self.assertIn('visuals',schemas['Certifications_ReviewedQuestion']['required'])
   # Upload visual response references UploadVisualReceipt
   up_vis=doc['paths']['/apps/certifications/v1/studies/{study_id}/questions/{question_id}/visuals']['post']
   self.assertEqual(up_vis['responses']['201']['content']['application/json']['schema']['$ref'],'#/components/schemas/Certifications_UploadVisualReceipt')
   # Pinned attempt visual endpoint
   att_vis=doc['paths']['/apps/certifications/v1/attempts/{attempt_id}/question_versions/{question_version_id}/visuals/{visual_id}']['get']
   self.assertEqual(att_vis['responses']['200']['headers']['Cache-Control']['schema']['example'],'private, no-store')
   self.assertEqual(att_vis['responses']['200']['headers']['X-Content-Type-Options']['schema']['example'],'nosniff')
   self.assertEqual(check_local_refs(doc),[])
   # Invalid workspace directory fails clearly
   res=subprocess.run(['python3',str(root/'tools/generate_docs.py'),'--workspace',str(root/'nonexistent-path')],capture_output=True,text=True)
   self.assertNotEqual(res.returncode,0)
   self.assertIn('Workspace directory not found',res.stderr+res.stdout)

def check_local_refs(doc):
 def find_all_refs(val):
  if isinstance(val,dict):
   for k,v in val.items():
    if k=='$ref':yield v
    else:yield from find_all_refs(v)
  elif isinstance(val,list):
   for item in val:yield from find_all_refs(item)
 schemas=doc.get('components',{}).get('schemas',{})
 dangling=[]
 for ref in sorted(set(find_all_refs(doc))):
  if ref.startswith('#/components/schemas/'):
   name=ref[len('#/components/schemas/'):]
   if name not in schemas:dangling.append(ref)
 return dangling

class IntegrityTests(unittest.TestCase):
 def test_whole_document_local_ref_integrity_on_real_artifact(self):
  doc=json.loads((ROOT/'src/presentation/assets/openapi.json').read_text())
  dangling=check_local_refs(doc)
  self.assertEqual(dangling,[],f"Found dangling local schema references in real artifact: {dangling}")
  schemas=doc['components']['schemas']
  self.assertIn('AnnotationsItemWrite',schemas)
  self.assertEqual(schemas['AnnotationsItemWrite']['required'],['expected_revision','item'])
  self.assertNotIn('AnnotationsEdit',schemas)
  self.assertEqual(doc['paths']['/apps/annotations/v1/instant/{code}/items']['post']['requestBody']['content']['application/json']['schema']['$ref'],'#/components/schemas/AnnotationsItemWrite')

 def test_fixture_annotations_instant_items_contract(self):
  with tempfile.TemporaryDirectory(prefix='annotations-doc-test-') as tmp:
   root=pathlib.Path(tmp);(root/'tools').mkdir();(root/'src/core').mkdir(parents=True);(root/'src/presentation/assets').mkdir(parents=True)
   shutil.copy(ROOT/'tools/generate_docs.py',root/'tools/generate_docs.py');shutil.copy(ROOT/'Cargo.toml',root/'Cargo.toml')
   for name in ['defaults.json','apps.json']:shutil.copy(ROOT/'src/core'/name,root/'src/core'/name)
   shutil.copy(ROOT/'src/presentation/assets/gateway_contracts.json',root/'src/presentation/assets/gateway_contracts.json')
   cert=root/'certifications_api/lib/presentation';cert.mkdir(parents=True)
   (cert/'mod.rs').write_text('pub fn router() { Router::new().route("/ready", get(ready)) }')
   repo=root/'annotations_api';(repo/'lib/presentation').mkdir(parents=True);(repo/'lib/domain').mkdir(parents=True)
   (repo/'lib/presentation/mod.rs').write_text('pub fn routes() { Router::new().route("/instant/{code}/items", post(add_item)) }')
   (repo/'lib/domain/rooms.rs').write_text('pub struct ItemWrite {\n pub expected_revision: i64,\n pub item: Value,\n}\n')
   res=subprocess.run(['python3',str(root/'tools/generate_docs.py'),'--workspace',str(root)],capture_output=True,text=True)
   self.assertEqual(res.returncode,0,res.stderr+res.stdout)
   doc=json.loads((root/'src/presentation/assets/openapi.json').read_text())
   schemas=doc['components']['schemas']
   self.assertIn('AnnotationsItemWrite',schemas)
   self.assertEqual(schemas['AnnotationsItemWrite']['required'],['expected_revision','item'])
   self.assertIn('expected_revision',schemas['AnnotationsItemWrite']['properties'])
   self.assertIn('item',schemas['AnnotationsItemWrite']['properties'])
   self.assertNotIn('kind',schemas['AnnotationsItemWrite']['properties'])
   self.assertNotIn('text',schemas['AnnotationsItemWrite']['properties'])
   self.assertNotIn('AnnotationsEdit',schemas)
   item_op=doc['paths']['/apps/annotations/v1/instant/{code}/items']['post']
   self.assertEqual(item_op['requestBody']['content']['application/json']['schema']['$ref'],'#/components/schemas/AnnotationsItemWrite')

 def test_fixture_local_ref_integrity(self):
  with tempfile.TemporaryDirectory(prefix='integrity-doc-test-') as tmp:
   root=pathlib.Path(tmp);(root/'tools').mkdir();(root/'src/core').mkdir(parents=True);(root/'src/presentation/assets').mkdir(parents=True)
   shutil.copy(ROOT/'tools/generate_docs.py',root/'tools/generate_docs.py');shutil.copy(ROOT/'Cargo.toml',root/'Cargo.toml')
   for name in ['defaults.json','apps.json']:shutil.copy(ROOT/'src/core'/name,root/'src/core'/name)
   shutil.copy(ROOT/'src/presentation/assets/gateway_contracts.json',root/'src/presentation/assets/gateway_contracts.json')
   cert=root/'certifications_api/lib/presentation';cert.mkdir(parents=True)
   (cert/'mod.rs').write_text('pub fn router() { Router::new().route("/ready", get(ready)) }')
   res=subprocess.run(['python3',str(root/'tools/generate_docs.py'),'--workspace',str(root)],capture_output=True,text=True)
   self.assertEqual(res.returncode,0,res.stderr+res.stdout)
   doc=json.loads((root/'src/presentation/assets/openapi.json').read_text())
   dangling=check_local_refs(doc)
   self.assertEqual(dangling,[],f"Found dangling local schema references in fixture: {dangling}")

 def test_fixture_annotations_prepared_certifications_contract(self):
  with tempfile.TemporaryDirectory(prefix='annotations-prep-test-') as tmp:
   root=pathlib.Path(tmp);(root/'tools').mkdir();(root/'src/core').mkdir(parents=True);(root/'src/presentation/assets').mkdir(parents=True)
   shutil.copy(ROOT/'tools/generate_docs.py',root/'tools/generate_docs.py');shutil.copy(ROOT/'Cargo.toml',root/'Cargo.toml')
   for name in ['defaults.json','apps.json']:shutil.copy(ROOT/'src/core'/name,root/'src/core'/name)
   shutil.copy(ROOT/'src/presentation/assets/gateway_contracts.json',root/'src/presentation/assets/gateway_contracts.json')
   cert=root/'certifications_api/lib/presentation';cert.mkdir(parents=True)
   (cert/'mod.rs').write_text('pub fn router() { Router::new().route("/ready", get(ready)) }')
   repo=root/'annotations_api';(repo/'lib/presentation').mkdir(parents=True);(repo/'lib/domain').mkdir(parents=True)
   (repo/'lib/presentation/mod.rs').write_text('pub fn routes() { Router::new().route("/me/notes/{note_id}/certifications/prepared", post(create_prepared_certification)) }')
   (repo/'lib/domain/notes.rs').write_text('''pub struct PreparedCertificationSourceInput {
    pub kind: Option<String>,
    pub file_id: Option<String>,
    pub revision_id: Option<String>,
    pub selection_kind: Option<String>,
    pub selection_spec: Option<String>,
}
pub struct PreparedCertificationConfigInput {
    pub language: Option<String>,
    pub count: Option<i64>,
}
pub struct PreparedCertificationInput {
    pub title: String,
    pub description: Option<String>,
    pub expected_revision: Option<i64>,
    pub sources: Vec<PreparedCertificationSourceInput>,
    pub config: Option<PreparedCertificationConfigInput>,
}
''')
   res=subprocess.run(['python3',str(root/'tools/generate_docs.py'),'--workspace',str(root)],capture_output=True,text=True)
   self.assertEqual(res.returncode,0,res.stderr+res.stdout)
   doc=json.loads((root/'src/presentation/assets/openapi.json').read_text())
   schemas=doc['components']['schemas']
   self.assertIn('AnnotationsPreparedCertificationInput',schemas)
   self.assertIn('AnnotationsPreparedCertificationSourceInput',schemas)
   self.assertIn('AnnotationsPreparedCertificationConfigInput',schemas)
   self.assertEqual(schemas['AnnotationsPreparedCertificationInput']['required'],['title','sources'])
   prep_op=doc['paths']['/apps/annotations/v1/me/notes/{note_id}/certifications/prepared']['post']
   self.assertEqual(prep_op['requestBody']['content']['application/json']['schema']['$ref'],'#/components/schemas/AnnotationsPreparedCertificationInput')
   self.assertEqual(prep_op['responses']['201']['content']['application/json']['schema']['$ref'],'#/components/schemas/Certifications_StudyDetail')

 def test_committed_artifact_annotations_prepared_certification_contract(self):
  doc=json.loads((ROOT/'src/presentation/assets/openapi.json').read_text())
  paths=doc.get('paths',{})
  prep_path='/apps/annotations/v1/me/notes/{note_id}/certifications/prepared'
  self.assertIn(prep_path,paths)
  prep_op=paths[prep_path]['post']
  self.assertEqual(prep_op['requestBody']['content']['application/json']['schema']['$ref'],'#/components/schemas/AnnotationsPreparedCertificationInput')
  self.assertEqual(prep_op['responses']['201']['content']['application/json']['schema']['$ref'],'#/components/schemas/Certifications_StudyDetail')
  schemas=doc.get('components',{}).get('schemas',{})
  self.assertIn('AnnotationsPreparedCertificationInput',schemas)
  self.assertIn('AnnotationsPreparedCertificationSourceInput',schemas)
  self.assertIn('AnnotationsPreparedCertificationConfigInput',schemas)
  self.assertEqual(schemas['AnnotationsPreparedCertificationInput']['required'],['title','sources'])
  self.assertEqual(prep_op.get('x-source-tree-sha256'),'9db4bdb797c65039014035bab6f0a13b1294f2b5b1612c50fe9584ea9ad39476')
  self.assertEqual(check_local_refs(doc),[])

 def test_committed_artifact_certifications_visual_routes_contract(self):
  doc=json.loads((ROOT/'src/presentation/assets/openapi.json').read_text())
  paths=doc.get('paths',{})

  # 1. visual_jobs
  vj_path='/apps/certifications/v1/studies/{study_id}/questions/{question_id}/visual_jobs'
  self.assertIn(vj_path,paths)
  vj_op=paths[vj_path]['post']
  self.assertEqual(vj_op['requestBody']['content']['application/json']['schema']['$ref'],'#/components/schemas/Certifications_PrepareVisualJobInput')
  self.assertEqual(vj_op['responses']['201']['content']['application/json']['schema']['$ref'],'#/components/schemas/Certifications_PreparedVisualJobResult')
  for code in ['201','401','403','404','409','410','422','503']:
   self.assertIn(code,vj_op['responses'])

  # 2. visuals
  vs_path='/apps/certifications/v1/studies/{study_id}/questions/{question_id}/visuals'
  self.assertIn(vs_path,paths)
  vs_op=paths[vs_path]['post']
  self.assertEqual(vs_op['requestBody']['content']['application/json']['schema']['$ref'],'#/components/schemas/Certifications_UploadVisualInput')
  self.assertEqual(vs_op['responses']['201']['content']['application/json']['schema']['$ref'],'#/components/schemas/Certifications_UploadVisualReceipt')
  for code in ['201','400','401','403','404','409','410','422','503']:
   self.assertIn(code,vs_op['responses'])

  # 3. visuals/{visual_id}
  vg_path='/apps/certifications/v1/studies/{study_id}/questions/{question_id}/visuals/{visual_id}'
  self.assertIn(vg_path,paths)
  vg_op=paths[vg_path]['get']
  self.assertIn('image/png',vg_op['responses']['200']['content'])
  self.assertEqual(vg_op['responses']['200']['headers']['Cache-Control']['schema']['example'],'no-store')
  self.assertIn('no-store',vg_op['responses']['200']['description'])
  for code in ['200','403','404','503']:
   self.assertIn(code,vg_op['responses'])

  # 3b. pinned attempt visual
  att_path='/apps/certifications/v1/attempts/{attempt_id}/question_versions/{question_version_id}/visuals/{visual_id}'
  self.assertIn(att_path,paths)
  att_op=paths[att_path]['get']
  self.assertIn('image/png',att_op['responses']['200']['content'])
  self.assertEqual(att_op['responses']['200']['headers']['Cache-Control']['schema']['example'],'private, no-store')
  self.assertEqual(att_op['responses']['200']['headers']['X-Content-Type-Options']['schema']['example'],'nosniff')
  for code in ['200','401','403','404','503']:
   self.assertIn(code,att_op['responses'])
  self.assertTrue(att_op['x-source'].startswith('certifications_api/lib/presentation/attempts.rs:'))
  self.assertEqual(att_op['x-source-tree-sha256'],'2aa0115335ab76c3f5a4bd89d41f1ce767586954cd16a36e36962582227608ba')

  # 4. legacy visual
  vl_path='/apps/certifications/v1/studies/{study_id}/questions/{question_id}/visual'
  self.assertIn(vl_path,paths)
  vl_op=paths[vl_path]['post']
  self.assertTrue(vl_op.get('deprecated'))
  self.assertNotIn('requestBody',vl_op)
  for code in ['403','404','409','422']:
   self.assertIn(code,vl_op['responses'])
  self.assertIn('deprecated_visual_endpoint',vl_op['responses']['422']['description'])

  # 5. DTO schemas and properties
  schemas=doc.get('components',{}).get('schemas',{})
  for s in ['Certifications_PrepareVisualJobInput','Certifications_PreparedVisualJobResult','Certifications_RenderJobDescriptor','Certifications_UploadVisualInput','Certifications_QuestionVisual','Certifications_UploadVisualReceipt','Certifications_AttemptVisualReference']:
   self.assertIn(s,schemas)

  self.assertEqual(schemas['Certifications_PrepareVisualJobInput']['required'],['template_id','template_version','mapping','config','rows'])
  self.assertEqual(schemas['Certifications_UploadVisualInput']['required'],['question_version_id','render_job_id','png_base64'])
  self.assertEqual(schemas['Certifications_RenderJobDescriptor']['required'],['job_id','template_id','template_version','mapping','config','rows','width','height','scale','expires_at'])
  self.assertEqual(schemas['Certifications_QuestionVisual']['required'],['id','mime_type','created_at'])
  self.assertNotIn('fsm_ref',schemas['Certifications_QuestionVisual']['properties'])
  self.assertNotIn('fsm_ref',schemas['Certifications_QuestionVisual'].get('required',[]))
  self.assertEqual(schemas['Certifications_UploadVisualReceipt']['required'],['id','mime_type','created_at','prepared_question_version_id','result_question_version_id','result_quiz_version_id'])
  self.assertEqual(schemas['Certifications_AttemptVisualReference']['required'],['id','mime_type','created_at'])
  self.assertEqual(schemas['Certifications_TakingQuestion']['properties']['visuals']['items']['$ref'],'#/components/schemas/Certifications_AttemptVisualReference')
  self.assertIn('visuals',schemas['Certifications_TakingQuestion']['required'])
  self.assertEqual(schemas['Certifications_ReviewedQuestion']['properties']['visuals']['items']['$ref'],'#/components/schemas/Certifications_AttemptVisualReference')
  self.assertIn('visuals',schemas['Certifications_ReviewedQuestion']['required'])
  self.assertEqual(check_local_refs(doc),[])

 def test_serde_skip_parser(self):
  with tempfile.TemporaryDirectory() as tmp:
   tpath=pathlib.Path(tmp)
   (tpath/'test.rs').write_text('''
pub struct ParserRegressionTarget {
    pub normal_field: String,
    #[serde(skip)]
    pub private_skip: String,
    #[serde(skip_serializing)]
    pub private_fsm_ref: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub config: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub default_config: Option<i64>,
}
''')
   import importlib.util
   spec=importlib.util.spec_from_file_location("generate_docs",ROOT/'tools/generate_docs.py')
   gd=importlib.util.module_from_spec(spec)
   spec.loader.exec_module(gd)
   gd.rust_models(tpath,source=".")
   target=gd.components.get('ParserRegressionTarget')
   self.assertIsNotNone(target)
   props=target['properties']
   req=target.get('required',[])
   self.assertIn('normal_field',props)
   self.assertIn('normal_field',req)
   self.assertNotIn('private_skip',props)
   self.assertNotIn('private_fsm_ref',props)
   self.assertIn('config',props)
   self.assertNotIn('config',req)
   self.assertIn('default_config',props)
   self.assertNotIn('default_config',req)

 def test_accepted_v2_routes_retained(self):
  doc_path=ROOT/'src/presentation/assets/openapi.json'
  self.assertTrue(doc_path.exists())
  doc=json.loads(doc_path.read_text())
  paths=doc.get('paths',{})
  self.assertGreaterEqual(len(paths),319)
  ops_count=sum(len(m) for m in paths.values())
  self.assertGreaterEqual(ops_count,432)
  # Notes accepted V2 routes
  self.assertIn('/apps/annotations/v1/me/content_jobs',paths)
  self.assertIn('/apps/annotations/v1/me/content_jobs/{job_id}',paths)
  self.assertIn('/apps/annotations/v1/me/content_jobs/{job_id}/events',paths)
  self.assertIn('/apps/annotations/v1/me/content_jobs/{job_id}/execution',paths)
  self.assertIn('/apps/annotations/v1/me/notes/{note_id}/reports',paths)
  self.assertIn('/apps/annotations/v1/me/tasks',paths)
  # Cortex remote sessions accepted V2 routes
  self.assertIn('/apps/cortex/v1/remote/sessions',paths)
  self.assertIn('/apps/cortex/v1/remote/sessions/{id}',paths)
  self.assertIn('/apps/cortex/v1/remote/sessions/{id}/approvals/{approval_id}',paths)
  self.assertIn('/apps/cortex/v1/remote/sessions/{id}/cancel',paths)
  self.assertIn('/apps/cortex/v1/remote/sessions/{session_id}/children',paths)
  # Reports accepted V2 routes
  self.assertIn('/apps/reports/v1/me/items/{id}',paths)
  self.assertIn('/apps/reports/v1/templates',paths)
  self.assertIn('/apps/reports/v1/render_jobs',paths)
  # Certifications accepted V2 visual route and source tree hash
  cert_att_path='/apps/certifications/v1/attempts/{attempt_id}/question_versions/{question_version_id}/visuals/{visual_id}'
  self.assertIn(cert_att_path,paths)
  cert_att_op=paths[cert_att_path]['get']
  self.assertEqual(cert_att_op.get('x-source-tree-sha256'),'2aa0115335ab76c3f5a4bd89d41f1ce767586954cd16a36e36962582227608ba')
  self.assertTrue(cert_att_op.get('x-source','').startswith('certifications_api/lib/presentation/attempts.rs'))

 def test_consumer_and_cortex_contract_corrections(self):
  doc=json.loads((ROOT/'src/presentation/assets/openapi.json').read_text())
  paths=doc.get('paths',{})
  schemas=doc.get('components',{}).get('schemas',{})

  # 1. Cortex 12 concrete operations and 2 graph operations
  cr_post=paths['/apps/cortex/v1/remote/sessions/{session_id}/children']['post']
  self.assertEqual(cr_post['responses']['201']['content']['application/json']['schema']['properties']['data']['$ref'],'#/components/schemas/Cortex_src_domain_services_agent_runs_ChildRun')
  self.assertNotIn('x-discovery-gaps',cr_post)

  cr_get=paths['/apps/cortex/v1/remote/sessions/{session_id}/children/{child_id}']['get']
  self.assertEqual(cr_get['responses']['200']['content']['application/json']['schema']['properties']['data']['$ref'],'#/components/schemas/Cortex_src_domain_services_agent_runs_ChildRun')

  cr_events=paths['/apps/cortex/v1/remote/sessions/{session_id}/children/{child_id}/events']['post']
  self.assertEqual(cr_events['responses']['200']['content']['application/json']['schema']['properties']['data']['$ref'],'#/components/schemas/Cortex_src_domain_services_agent_runs_ChildRunEvent')

  cr_cancel=paths['/apps/cortex/v1/remote/sessions/{session_id}/children/{child_id}/cancel']['post']
  self.assertEqual(cr_cancel['responses']['202']['content']['application/json']['schema']['properties']['data']['$ref'],'#/components/schemas/Cortex_src_domain_services_agent_runs_ChildRunEvent')

  cr_act=paths['/apps/cortex/v1/remote/sessions/{session_id}/children/{child_id}/actions']['post']
  self.assertEqual(cr_act['responses']['201']['content']['application/json']['schema']['properties']['data']['$ref'],'#/components/schemas/Cortex_src_domain_services_agent_runs_ChildRunEvent')

  cr_ans=paths['/apps/cortex/v1/remote/sessions/{session_id}/children/{child_id}/actions/{action_id}/answer']['post']
  self.assertEqual(cr_ans['responses']['200']['content']['application/json']['schema']['properties']['data']['$ref'],'#/components/schemas/Cortex_src_domain_services_agent_runs_ChildRunEvent')

  b_child=paths['/apps/cortex/v1/remote/sessions/{remote_session_id}/outputs/{chat_session_id}/{output_id}/children']['post']
  self.assertIn('201',b_child['responses'])
  self.assertIn('200',b_child['responses'])
  self.assertEqual(b_child['responses']['201']['content']['application/json']['schema']['properties']['data']['$ref'],'#/components/schemas/Cortex_src_presentation_agent_runs_BoundChildView')

  b_act=paths['/apps/cortex/v1/remote/sessions/{remote_session_id}/outputs/{chat_session_id}/{output_id}/actions']['post']
  self.assertEqual(b_act['responses']['201']['content']['application/json']['schema']['properties']['data']['$ref'],'#/components/schemas/Cortex_src_presentation_agent_runs_OutputActionView')

  tool_res=paths['/apps/cortex/v1/chats/{session_id}/outputs/{output_id}/tool-results']['post']
  self.assertIn('202',tool_res['responses'])
  self.assertEqual(tool_res['responses']['202']['content']['application/json']['schema']['properties']['data']['required'],['session_id','output_id','call_id'])
  self.assertNotIn('x-discovery-gaps',tool_res)

  mg=paths['/apps/cortex/v1/memory-graph']['get']
  self.assertIn('x-discovery-gaps',mg)
  self.assertEqual(mg['x-discovery-gaps'],['Upstream Hippocampus node/edge metadata fields vary by memory type and are passed through.'])

  # 2. Reports consumer schemas & integer scale
  embed_op=paths['/apps/reports/v1/projects/{project}/reports/{report}/cards/{dataset}/embed']['get']
  self.assertEqual(embed_op['responses']['200']['content']['application/json']['schema']['$ref'],'#/components/schemas/ViewerEmbedDescriptor')

  rj_post=paths['/apps/reports/v1/render_jobs']['post']
  self.assertEqual(rj_post['responses']['201']['content']['application/json']['schema']['$ref'],'#/components/schemas/RenderJob')

  scale_prop=schemas['CreateRenderJobInput']['properties']['scale']
  self.assertEqual(scale_prop['anyOf'],[{'type':'integer'},{'type':'null'}])

  # 3. Notes mutation contracts
  notes_post=paths['/apps/annotations/v1/me/notes']['post']
  self.assertIn('201',notes_post['responses'])
  self.assertIn('200',notes_post['responses'])
  self.assertIn('ETag',notes_post['responses']['201']['headers'])

  note_put=paths['/apps/annotations/v1/me/notes/{note_id}']['put']
  self.assertTrue(any(p.get('name')=='If-Match' and p.get('in')=='header' for p in note_put.get('parameters',[])))
  self.assertIn('ETag',note_put['responses']['200']['headers'])

  note_del=paths['/apps/annotations/v1/me/notes/{note_id}']['delete']
  self.assertTrue(any(p.get('name')=='If-Match' and p.get('in')=='header' for p in note_del.get('parameters',[])))
  self.assertIn('204',note_del['responses'])
  self.assertEqual(note_del['responses']['200']['content']['application/json']['schema']['$ref'],'#/components/schemas/AnnotationsDeleteNoteOutcome')

  ref_post=paths['/apps/annotations/v1/me/notes/{note_id}/reports']['post']
  self.assertIn('201',ref_post['responses'])
  self.assertEqual(ref_post['requestBody']['content']['application/json']['schema']['$ref'],'#/components/schemas/AnnotationsRegisterReportReferenceInput')

  # 4. README pinned accepted source
  readme=(ROOT/'README.md').read_text()
  self.assertIn('78e6f489edeed7508c5be5b0889abf79c9d1a17e',readme)
  self.assertNotIn('accepted source `bb6b70e5`',readme)

if __name__=='__main__':unittest.main()
