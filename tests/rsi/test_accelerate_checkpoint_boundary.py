"""Benign CPU public-API regressions for the maintained Accelerate checkpoint patch."""
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock
os.environ['CUDA_VISIBLE_DEVICES']='-1'
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
try:
    import torch
    from safetensors.torch import save_file
    from accelerate import load_checkpoint_and_dispatch
    from accelerate.utils import modeling
except ModuleNotFoundError as error:
    raise unittest.SkipTest("Dedicated CPU dependency lane supplies Torch and the private Accelerate wheel") from error
BASE=Path(tempfile.mkdtemp(prefix="hermes-checkpoint-cpu-"))

def link_directory(link, target):
    if os.name == 'nt':
        import subprocess
        made = subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(link),str(target)],
                              capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        if made.returncode:
            raise AssertionError("Native junction setup failed; this is not a passing test")
    else:
        link.symlink_to(target, target_is_directory=True)

class CheckpointIndexBoundary(unittest.TestCase):
    def folder(self):
        root=BASE/'cases'/uuid.uuid4().hex
        root.mkdir(parents=True)
        return root
    def apis(self):
        return [('load_checkpoint_in_model',modeling.load_checkpoint_in_model),('load_checkpoint_and_dispatch',load_checkpoint_and_dispatch)]
    def invoke(self,api,checkpoint):
        model=torch.nn.Linear(2,2)
        api(model,str(checkpoint),device_map={'':'cpu'})
        return model
    def test_reject_untrusted_shard_paths_before_any_load(self):
        for name,api in self.apis():
            for kind in ['parent','absolute','drive-relative','win-absolute','unc','device-pipe','backslash-parent','empty','nul','directory','wrong-type','alternate-stream','mixed-valid-invalid']:
                with self.subTest(api=name,kind=kind):
                    root=self.folder()
                    torch.save(torch.nn.Linear(2,2).state_dict(),root/'outside.bin')
                    checkpoints=root/'checkpoint'
                    checkpoints.mkdir()
                    torch.save(torch.nn.Linear(2,2).state_dict(),checkpoints/'valid.bin')
                    (checkpoints/'directory').mkdir()
                    names={'parent':'../outside.bin','absolute':str(root/'outside.bin'),'drive-relative':'C:outside.bin','win-absolute':r'C:\outside.bin','unc':r'\\server\share\outside.bin','device-pipe':r'\\.\pipe\checkpoint','backslash-parent':r'..\outside.bin','empty':'','nul':'bad\x00.bin','directory':'directory','wrong-type':['valid.bin'],'alternate-stream':'valid.bin:stream','mixed-valid-invalid':'../outside.bin'}
                    entries={'weight':names[kind]}
                    if kind=='mixed-valid-invalid':
                        entries['bias']='valid.bin'
                    index=checkpoints/'model.index.json'
                    index.write_text(json.dumps({'weight_map':entries}),encoding='utf-8')
                    with mock.patch.object(modeling,'load_state_dict',wraps=modeling.load_state_dict) as sink:
                        with self.assertRaises(ValueError):
                            self.invoke(api,index)
                        self.assertEqual(sink.call_count,0)
    def test_malformed_indexes_are_rejected_before_loading(self):
        for name,api in self.apis():
            for document in [[],{'weight_map':[]},{'weight_map':None},{'weight_map':{'weight':12}}]:
                with self.subTest(api=name,document=document):
                    root=self.folder()
                    index=root/'custom.json'
                    index.write_text(json.dumps(document),encoding='utf-8')
                    with mock.patch.object(modeling,'load_state_dict',wraps=modeling.load_state_dict) as sink:
                        with self.assertRaises(ValueError): self.invoke(api,index)
                        self.assertEqual(sink.call_count,0)
    def test_actual_windows_junction_escape_is_rejected(self):
        import subprocess
        for name,api in self.apis():
            with self.subTest(api=name):
                root=self.folder()
                outside=root/'outside'
                outside.mkdir()
                torch.save(torch.nn.Linear(2,2).state_dict(),outside/'weights.bin')
                checkpoint=root/'checkpoint'
                checkpoint.mkdir()
                junction=checkpoint/'linked'
                link_directory(junction, outside)
                index=checkpoint/'model.index.json'
                index.write_text(json.dumps({'weight_map':{'weight':'linked/weights.bin'}}),encoding='utf-8')
                with mock.patch.object(modeling,'load_state_dict',wraps=modeling.load_state_dict) as sink:
                    with self.assertRaises(ValueError): self.invoke(api,index)
                    self.assertEqual(sink.call_count,0)
    def test_native_hub_junction_keeps_safetensors(self):
        import subprocess
        import huggingface_hub.constants as constants
        for name,api in self.apis():
            for nested_index in [False,True]:
              with self.subTest(api=name,nested_index=nested_index):
                root=self.folder()
                cache=root/'hub'
                repo=cache/'models--test--local'
                snapshot=repo/'snapshots'/('a'*40)
                snapshot.mkdir(parents=True)
                if nested_index:
                    snapshot=snapshot/'subfolder'
                    snapshot.mkdir()
                blobs=repo/'blobs'
                blobs.mkdir()
                original=torch.nn.Linear(2,2).state_dict()
                save_file(original,str(blobs/'weights.safetensors'),metadata={'format':'pt'})
                link_directory(snapshot/'linked', blobs)
                index=snapshot/'model.index.json'
                index.write_text(json.dumps({'weight_map':{k:'linked/weights.safetensors' for k in original}}),encoding='utf-8')
                with mock.patch.object(constants,'HF_HUB_CACHE',str(cache)):
                    loaded=self.invoke(api,index).state_dict()
                    for key,value in original.items(): torch.testing.assert_close(loaded[key],value,rtol=0,atol=0)
                # An explicit caller-selected cache remains usable independently of the default.
                with mock.patch.object(constants,'HF_HUB_CACHE',str(root/'different-cache')):
                    custom=self.invoke(api,index).state_dict()
                    for key,value in original.items(): torch.testing.assert_close(custom[key],value,rtol=0,atol=0)
    def test_utf8_index_under_native_default_encoding(self):
        if os.name == 'nt':
            import locale
            self.assertNotEqual(locale.getpreferredencoding(False).lower().replace('-', ''), 'utf8')
        for name,api in self.apis():
            with self.subTest(api=name):
                root=self.folder()
                original=torch.nn.Linear(2,2).state_dict()
                torch.save(original,root/'日本語.bin')
                index=root/'custom.json'
                index.write_text(json.dumps({'weight_map':{k:'日本語.bin' for k in original}},ensure_ascii=False),encoding='utf-8')
                loaded=self.invoke(api,index).state_dict()
                for key,value in original.items(): torch.testing.assert_close(loaded[key],value,rtol=0,atol=0)
    def test_receiver_rank_does_not_require_local_shard(self):
        import torch.distributed.checkpoint.state_dict as state_dict
        for name,api in self.apis():
            for rank,path in [(1,'absent.bin'),(0,'absent.bin'),(1,'../outside.bin')]:
                with self.subTest(api=name,rank=rank,shard=path):
                    root=self.folder()
                    index=root/'model.index.json'
                    index.write_text(json.dumps({'weight_map':{'weight':path}}),encoding='utf-8')
                    with mock.patch.object(modeling.dist,'get_rank',return_value=rank), mock.patch.object(state_dict,'set_model_state_dict') as publish, mock.patch.object(modeling,'load_state_dict',wraps=modeling.load_state_dict) as sink:
                        if rank==1 and path=='absent.bin':
                            api(torch.nn.Linear(2,2),str(index),device_map=None,broadcast_from_rank0=True)
                            publish.assert_called_once()
                            self.assertEqual(publish.call_args.args[1],{})
                        else:
                            with self.assertRaises(ValueError):
                                api(torch.nn.Linear(2,2),str(index),device_map=None,broadcast_from_rank0=True)
                            publish.assert_not_called()
                        sink.assert_not_called()
    def test_legitimate_checkpoints_keep_exact_tensors(self):
        for name,api in self.apis():
            for mode in ['direct-bin','direct-safe','folder-bin','folder-safe','sharded-bin','sharded-safe','flat-index','duplicate-shard']:
                with self.subTest(api=name,mode=mode):
                    root=self.folder()
                    original=torch.nn.Linear(2,2).state_dict()
                    if mode.startswith('direct') or mode.startswith('folder'):
                        path=root/('model.safetensors' if mode.endswith('safe') else 'pytorch_model.bin')
                        if mode.endswith('safe'): save_file(original,str(path),metadata={'format':'pt'})
                        else: torch.save(original,path)
                        checkpoint=root if mode.startswith('folder') else path
                    else:
                        nested=root/'日本語 shards'
                        nested.mkdir()
                        entries={}
                        if mode=='duplicate-shard':
                            path=nested/'all.bin'
                            torch.save(original,path)
                            entries={k:str(path.relative_to(root)) for k in original}
                        else:
                            for key,value in original.items():
                                path=nested/(key+('.safetensors' if mode=='sharded-safe' else '.bin'))
                                if mode=='sharded-safe': save_file({key:value},str(path),metadata={'format':'pt'})
                                else: torch.save({key:value},path)
                                entries[key]=str(path.relative_to(root))
                        index=root/'model.index.json'
                        index.write_text(json.dumps(entries if mode=='flat-index' else {'metadata':{},'weight_map':entries},ensure_ascii=True),encoding='utf-8')
                        checkpoint=index
                    loaded=self.invoke(api,checkpoint).state_dict()
                    for key,value in original.items(): torch.testing.assert_close(loaded[key],value,rtol=0,atol=0)
if __name__ == '__main__':
    class CountedResult(unittest.TextTestResult):
        subcases = 0
        def addSubTest(self, test, subtest, error):
            self.subcases += 1
            super().addSubTest(test, subtest, error)
    result = unittest.TextTestRunner(verbosity=2, resultclass=CountedResult).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(CheckpointIndexBoundary))
    print(json.dumps({"torch": torch.__version__, "source": modeling.__file__,
                      "tests": result.testsRun, "subcases": result.subcases,
                      "failures": len(result.failures), "errors": len(result.errors),
                      "skipped": len(result.skipped)}))
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
