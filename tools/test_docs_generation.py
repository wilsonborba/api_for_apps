"""Read-only source fixtures prove additions, changes, removals and absent-service reporting."""
import unittest,tempfile,pathlib,subprocess,json,shutil
ROOT=pathlib.Path(__file__).resolve().parents[1]
class DiscoveryTests(unittest.TestCase):
 def test_fixture_route_lifecycle(self):
  # Run a copy of the generator so tests never modify central production contracts.
  with tempfile.TemporaryDirectory(prefix='asodya-doc-test-') as tmp:
   root=pathlib.Path(tmp);(root/'tools').mkdir();(root/'src/core').mkdir(parents=True);(root/'src/presentation/assets').mkdir(parents=True);shutil.copy(ROOT/'tools/generate_docs.py',root/'tools/generate_docs.py')
   shutil.copy(ROOT/'Cargo.toml',root/'Cargo.toml')
   for f in ['defaults.json','apps.json']:shutil.copy(ROOT/'src/core'/f,root/'src/core'/f)
   shutil.copy(ROOT/'src/presentation/assets/gateway_contracts.json',root/'src/presentation/assets/gateway_contracts.json');repo=root/'certifications_api';repo.mkdir();route=repo/'routes.py'
   def generate():
    subprocess.run(['python3',str(root/'tools/generate_docs.py'),'--workspace',str(root)],check=True,capture_output=True);return json.loads((root/'src/presentation/assets/openapi.json').read_text())
   annotations=root/'annotations_api/lib/presentation';annotations.mkdir(parents=True);(annotations/'mod.rs').write_text('pub fn router() { Router::new().route("/health", get(health)).route("/instant/{code}", get(read).put(create)) }')
   route.write_text('from fastapi import APIRouter\nfrom pydantic import BaseModel\nclass FixtureRequest(BaseModel):\n title: str\nr=APIRouter(prefix="/fixture")\n@r.get("/one")\ndef one(q: str):\n return {"answer":q}\n@r.post("/typed")\ndef typed(payload: FixtureRequest):\n return {"ok": True}\n');v=generate();self.assertEqual(v['paths']['/apps/annotations/v1/instant/{code}']['put']['security'],[]);self.assertIn('/apps/annotations/v1/health',v['paths']);self.assertIn('/apps/certifications/v1/fixture/one',v['paths']);self.assertIn('requestBody',v['paths']['/apps/certifications/v1/fixture/typed']['post'])
   offline=root/'certifications-offline';repo.rename(offline);cached=generate();self.assertIn('/apps/certifications/v1/fixture/one',cached['paths']);offline.rename(repo)
   route.write_text(route.read_text().replace('/one','/two'));v=generate();self.assertNotIn('/apps/certifications/v1/fixture/one',v['paths']);self.assertIn('/apps/certifications/v1/fixture/two',v['paths'])
   route.unlink();v=generate();self.assertNotIn('/apps/certifications/v1/fixture/two',v['paths'])

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

if __name__=='__main__':unittest.main()
