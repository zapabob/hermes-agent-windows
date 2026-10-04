"""Real-model equivalence for bounded-logit allocation."""
import torch
from transformers import Qwen2Config, Qwen2ForCausalLM
import frozen_evaluator as evaluator

torch.set_num_threads(1)


def test_last_token_logits_preserves_real_model_decision():
    assert hasattr(evaluator, "last_token_logits"), "Bounded last-token forward is not implemented"
    torch.manual_seed(9)
    model = Qwen2ForCausalLM(Qwen2Config(vocab_size=64, hidden_size=16, intermediate_size=32, num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=2))
    model.eval()
    inputs = {"input_ids": torch.tensor([[1, 2, 3, 4]])}
    with torch.inference_mode():
        full = model(**inputs, use_cache=False).logits[0, -1].float()
        bounded = evaluator.last_token_logits(model, inputs)
    torch.testing.assert_close(bounded, full, rtol=1e-5, atol=1e-7)
    assert int(bounded.argmax()) == int(full.argmax())


def test_sparse_response_loss_and_gradients_match_full_response_only_loss():
    assert hasattr(evaluator, "response_only_loss"), "Sparse response-only loss is not implemented"
    torch.manual_seed(11)
    model = Qwen2ForCausalLM(Qwen2Config(vocab_size=64, hidden_size=16, intermediate_size=32, num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=2))
    model.eval()
    values = {"input_ids": torch.tensor([[1, 2, 3, 4, 5, 6]]), "labels": torch.tensor([[-100, -100, -100, -100, 5, 6]])}
    reference = model(**values, use_cache=False).loss
    reference.backward()
    gradients = {name: parameter.grad.clone() for name, parameter in model.named_parameters()}
    model.zero_grad(set_to_none=True)
    sparse = evaluator.response_only_loss(model, values)
    sparse.backward()
    torch.testing.assert_close(sparse, reference, rtol=1e-5, atol=1e-7)
    for name, parameter in model.named_parameters():
        torch.testing.assert_close(parameter.grad, gradients[name], rtol=1e-4, atol=1e-7)
