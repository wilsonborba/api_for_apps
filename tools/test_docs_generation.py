"""Read-only source fixtures prove additions, changes, removals and absent-service reporting."""
import unittest,tempfile,pathlib,subprocess,json,shutil
ROOT=pathlib.Path(__file__).resolve().parents[1]
class DiscoveryTests(unittest.TestCase):
 def test_fixture_route_lifecycle(self):
  # Run a copy of the generator so tests never modify central production contracts.
  with tempfile.TemporaryDirectory(prefix='asodya-doc-test-') as tmp:
   root=pathlib.Path(tmp);(root/'tools').mkdir();(root/'src/core').mkdir(parents=True);(root/'src/presentation/assets').mkdir(parents=True);shutil.copy(ROOT/'tools/generate_docs.py',root/'tools/generate_docs.py')
   for f in ['defaults.json','apps.json']:shutil.copy(ROOT/'src/core'/f,root/'src/core'/f)
   shutil.copy(ROOT/'src/presentation/assets/gateway_contracts.json',root/'src/presentation/assets/gateway_contracts.json');repo=root/'certifications_api';repo.mkdir();route=repo/'routes.py'
   def generate():
    subprocess.run(['python3',str(root/'tools/generate_docs.py'),'--workspace',str(root)],check=True,capture_output=True);return json.loads((root/'src/presentation/assets/openapi.json').read_text())
   route.write_text('from fastapi import APIRouter\nr=APIRouter(prefix="/fixture")\n@r.get("/one")\ndef one(q: str):\n return {"answer":q}\n');v=generate();self.assertIn('/apps/certifications/v1/fixture/one',v['paths'])
   route.write_text(route.read_text().replace('/one','/two'));v=generate();self.assertNotIn('/apps/certifications/v1/fixture/one',v['paths']);self.assertIn('/apps/certifications/v1/fixture/two',v['paths'])
   route.unlink();v=generate();self.assertNotIn('/apps/certifications/v1/fixture/two',v['paths'])
if __name__=='__main__':unittest.main()
