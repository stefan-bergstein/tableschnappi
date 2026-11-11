"""Regression checks for identity, hook lifecycle, prompt preservation and source pins.

Run with Python + PyYAML + Helm; no cluster or MLflow installation required.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import yaml

CHART = Path(__file__).resolve().parents[1]


def render(*values, profile="values-multi-user.yaml", namespace="tableschnappi-user01"):
    command = ["helm", "template", "tableschnappi", str(CHART), "--namespace", namespace]
    if profile:
        command += ["-f", str(CHART / profile)]
    for value in values:
        flag = "--set" if value.partition("=")[2] in ("true", "false") else "--set-string"
        command += [flag, value]
    return [obj for obj in yaml.safe_load_all(subprocess.check_output(command, text=True)) if obj]


def by_kind(objects, kind):
    return [obj for obj in objects if obj["kind"] == kind]


class WorkshopTests(unittest.TestCase):
    def test_all_participants_use_own_identity_and_workspace(self):
        for number in range(1, 51):
            user = f"user{number:02d}"
            namespace = "tableschnappi-" + user
            objects = render(f"workbench.name={user}", f"workbench.username={user}", namespace=namespace)
            self.assertTrue(all(obj["metadata"]["namespace"] == namespace for obj in objects))
            notebook = by_kind(objects, "Notebook")[0]
            self.assertEqual(notebook["metadata"]["annotations"]["opendatahub.io/mlflow-instance"], "mlflow")
            self.assertEqual(notebook["metadata"]["annotations"]["opendatahub.io/username"], user)
            self.assertEqual(notebook["spec"]["template"]["spec"]["serviceAccountName"], user)
            self.assertFalse(by_kind(objects, "DataSciencePipelinesApplication"))
            self.assertFalse(any("import-pipeline" in obj["metadata"]["name"] for obj in objects))
            for binding in by_kind(objects, "RoleBinding"):
                self.assertEqual(binding["roleRef"]["kind"], "ClusterRole")
                for subject in binding["subjects"]:
                    if subject["kind"] == "User":
                        self.assertEqual(subject["name"], user)
                    else:
                        self.assertEqual(subject["namespace"], namespace)
            assistant = next(obj for obj in by_kind(objects, "Deployment") if obj["metadata"]["name"].endswith("mlflow-proxy"))
            env = {e["name"]: e for e in assistant["spec"]["template"]["spec"]["containers"][0]["env"]}
            self.assertEqual(env["MLFLOW_WORKSPACE"]["value"], namespace)
            self.assertEqual(env["OPENAI_API_KEY"]["valueFrom"]["secretKeyRef"]["key"], "api_key")
            for deployment in by_kind(objects, "Deployment"):
                self.assertIn("@sha256:", deployment["spec"]["template"]["spec"]["containers"][0]["image"])
            for job in by_kind(objects, "Job"):
                self.assertIn("post-install", job["metadata"]["annotations"]["helm.sh/hook"])
            for obj in by_kind(objects, "ServiceAccount") + by_kind(objects, "RoleBinding"):
                self.assertNotIn("helm.sh/hook", obj["metadata"].get("annotations", {}))

    def test_generated_secret_is_release_owned_and_uses_selected_key(self):
        objects = render("model.existingSecret=", "model.apiKey=dummy")
        secret = by_kind(objects, "Secret")[0]
        self.assertEqual(secret["stringData"], {"api_key": "dummy"})
        self.assertNotIn("helm.sh/hook", secret["metadata"].get("annotations", {}))

    def test_mlflow_off_leaves_no_integration_or_seed(self):
        objects = render("mlflow.enabled=false", "workbench.grantEdit=false")
        self.assertFalse(by_kind(objects, "RoleBinding"))
        notebook = by_kind(objects, "Notebook")[0]
        self.assertNotIn("opendatahub.io/mlflow-instance", notebook["metadata"]["annotations"])
        self.assertFalse(any("mlflow" in obj["metadata"]["name"] for obj in by_kind(objects, "Job")))

    def test_mlflow_only_hooks_have_a_service_account(self):
        objects = render("assistant.enabled=false")
        accounts = {obj["metadata"]["name"] for obj in by_kind(objects, "ServiceAccount")}
        for job in by_kind(objects, "Job"):
            if "mlflow" in job["metadata"]["name"]:
                self.assertIn(job["spec"]["template"]["spec"]["serviceAccountName"], accounts)

    def test_asset_and_all_model_consumers_use_same_secret(self):
        objects = render("garak.enabled=true")
        asset = next(obj for obj in by_kind(objects, "ConfigMap") if obj["metadata"]["name"] == "gen-ai-aa-custom-model-endpoints")
        provider = yaml.safe_load(asset["data"]["config.yaml"])["providers"]["inference"][0]
        self.assertEqual(provider["config"]["custom_gen_ai"]["api_key"]["secretRef"], {"name": "model-api-key", "key": "api_key"})
        def check(value):
            if isinstance(value, dict):
                if "secretKeyRef" in value and value["secretKeyRef"]["name"] == "model-api-key":
                    self.assertEqual(value["secretKeyRef"]["key"], "api_key")
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)
        check(objects)

    def test_qwen_body_can_be_disabled_for_other_providers(self):
        objects = render("model.extraBody=false")
        config = next(obj for obj in by_kind(objects, "ConfigMap") if obj["metadata"]["name"].endswith("guardrails-config"))
        parameters = yaml.safe_load(config["data"]["config.yaml"])["models"][0]["parameters"]
        self.assertNotIn("extra_body", parameters)

    def test_source_pin_preserves_edits_and_retries_interrupted_fetch(self):
        notebook = by_kind(render(), "Notebook")[0]
        init = notebook["spec"]["template"]["spec"]["initContainers"][0]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo, target = base / "repository", base / "target"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "lesson.txt").write_text("pinned lesson")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture"], check=True)
            commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            (repo / "lesson.txt").write_text("newer unreviewed source")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "new head"], check=True)
            script = init["command"][-1].replace("/opt/app-root/src/tableschnappi", str(target))
            env = {**os.environ, "SOURCE_REPOSITORY": str(repo), "SOURCE_REF": commit, "GITHUB_TOKEN": ""}
            env["SOURCE_REF"] = "missing-ref"
            self.assertNotEqual(subprocess.run(["bash", "-ec", script], env=env, capture_output=True).returncode, 0)
            env["SOURCE_REF"] = commit
            subprocess.run(["bash", "-ec", script], env=env, check=True, capture_output=True)
            self.assertEqual((target / "lesson.txt").read_text(), "pinned lesson")
            (target / "lesson.txt").write_text("participant edit")
            subprocess.run(["bash", "-ec", script], env=env, check=True, capture_output=True)
            self.assertEqual((target / "lesson.txt").read_text(), "participant edit")

    def test_configmap_source_preserves_existing_pvc_content(self):
        objects = render("workbench.sourceConfigMap=workshop-source", "workbench.seedFiles={lesson.ipynb}")
        notebook = by_kind(objects, "Notebook")[0]
        spec = notebook["spec"]["template"]["spec"]
        self.assertIn({"name": "seed", "configMap": {"name": "workshop-source"}}, spec["volumes"])
        import tarfile
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            seed, pvc, archive = base / "seed", base / "pvc", base / "archive"
            for folder in (seed, pvc, archive):
                folder.mkdir()
            (archive / "lesson.txt").write_text("initial source")
            with tarfile.open(seed / "source.tar.gz", "w:gz") as stream:
                stream.add(archive / "lesson.txt", arcname="lesson.txt")
            (seed / "SOURCE_COMMIT").write_text("source revision")
            (seed / "lesson.ipynb").write_text("initial notebook")
            script = spec["initContainers"][0]["command"][-1]
            script = script.replace("/opt/app-root/src", str(pvc)).replace("/seed/", str(seed) + "/")
            subprocess.run(["bash", "-ec", script], check=True)
            self.assertEqual((pvc / "tableschnappi/lesson.txt").read_text(), "initial source")
            (pvc / "tableschnappi/lesson.txt").write_text("participant source")
            (pvc / "lesson.ipynb").write_text("participant notebook")
            (pvc / ".tableschnappi-source").unlink()
            subprocess.run(["bash", "-ec", script], check=True)
            self.assertEqual((pvc / "tableschnappi/lesson.txt").read_text(), "participant source")
            self.assertEqual((pvc / "lesson.ipynb").read_text(), "participant notebook")

    def test_seed_preserves_existing_prompts_and_propagates_other_errors(self):
        code = (CHART / "files/seed-mlflow.py").read_text()
        class Error(Exception):
            def __init__(self, code):
                self.error_code = code
        for state in (None, types.SimpleNamespace(version=7), "PERMISSION_DENIED"):
            calls = []
            module = types.ModuleType("mlflow")
            module.set_tracking_uri = lambda uri: None
            module.set_experiment = lambda name: None
            def load(uri):
                if state is None or isinstance(state, str):
                    raise Error(state or "RESOURCE_DOES_NOT_EXIST")
                return state
            def register(**kwargs):
                calls.append(kwargs)
                return types.SimpleNamespace(version=1)
            module.genai = types.SimpleNamespace(load_prompt=load, register_prompt=register)
            errors = types.ModuleType("mlflow.exceptions")
            errors.MlflowException = Error
            with patch.dict(sys.modules, {"mlflow": module, "mlflow.exceptions": errors}), patch.dict(os.environ, {"MLFLOW_TRACKING_URI": "https://mlflow.example.com", "MLFLOW_EXPERIMENT": "test"}):
                if isinstance(state, str):
                    with self.assertRaises(Error):
                        exec(compile(code, "seed-mlflow.py", "exec"), {})
                else:
                    exec(compile(code, "seed-mlflow.py", "exec"), {})
            self.assertEqual(len(calls), 1 if state is None else 0)


if __name__ == "__main__":
    unittest.main()
