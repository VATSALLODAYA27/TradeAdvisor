"""Deliverable 2, second half: LoRA fine-tune of the selected base model on the reasoning-chain dataset.

Runs on a free Google Colab T4 GPU (or any 16 GB card), never on this PC. Steps:
  1. Build the data here:  .venv\\Scripts\\python.exe -m slm.dataset 400
  2. In Colab: upload slm/data/desk_instructions.jsonl, then  !pip install unsloth  and run this file.
  3. It saves a LoRA adapter and a 4-bit GGUF. Serve it from any OpenAI-compatible host and point the desk at it with
     SLM_BASE_URL, SLM_MODEL and SLM_API_KEY; model.py and the guardrails stay the same.
"""
from datasets import load_dataset
from trl import SFTConfig, SFTTrainer
from unsloth import FastLanguageModel

BASE = "unsloth/gpt-oss-20b"  # selected by slm/evaluate.py
model, tok = FastLanguageModel.from_pretrained(BASE, max_seq_length=8192, load_in_4bit=True)
model = FastLanguageModel.get_peft_model(model, r=16, lora_alpha=32, lora_dropout=0, target_modules=[
    "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"], use_gradient_checkpointing="unsloth")

data = load_dataset("json", data_files="desk_instructions.jsonl", split="train").train_test_split(test_size=0.05, seed=7)
fmt = lambda b: {"text": [tok.apply_chat_template(m, tokenize=False) for m in b["messages"]]}  # keeps the "thinking" chain
train, test = data["train"].map(fmt, batched=True), data["test"].map(fmt, batched=True)

SFTTrainer(model=model, tokenizer=tok, train_dataset=train, eval_dataset=test, args=SFTConfig(
    dataset_text_field="text", per_device_train_batch_size=1, gradient_accumulation_steps=8, num_train_epochs=2,
    learning_rate=2e-4, logging_steps=10, eval_strategy="epoch", output_dir="desk-lora", report_to="none")).train()

model.save_pretrained("desk-lora")
tok.save_pretrained("desk-lora")
model.save_pretrained_gguf("desk-gguf", tok, quantization_method="q4_k_m")  # quantised for consumer-GPU serving
