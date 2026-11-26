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
}''')
   (repo/'lib/domain/studies.rs').write_text('''pub struct PreparedStudyConfig {
    pub language: String,
    pub count: i64,
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
   # /me/quizzes/{quiz_id}/statistics is session-protected
   my_stats=doc['paths']['/apps/certifications/v1/me/quizzes/{quiz_id}/statistics']['get']
   self.assertEqual(my_stats['x-access-level'],'session')
   self.assertEqual(my_stats['security'],[{'SessionCookie':[]}])
   # /quizzes/{quiz_id}/statistics is public
   pub_stats=doc['paths']['/apps/certifications/v1/quizzes/{quiz_id}/statistics']['get']
   self.assertEqual(pub_stats['x-access-level'],'public')
   self.assertEqual(pub_stats['security'],[])
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

if __name__=='__main__':unittest.main()
