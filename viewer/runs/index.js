window.RUN_INDEX = [
 {
  "id": "seed11-live-oracle",
  "label": "seed 11 \u00b7 21d \u00b7 Nemotron-3.5-Lightning-30B-A3B \u00b7 oracle extraction",
  "mode": "live",
  "seed": 11,
  "days": 21,
  "extract": "oracle",
  "product": "Driftnote",
  "agent_model": "nvidia/Nemotron-3.5-Lightning-30B-A3B",
  "updated": 1792279063.2017443,
  "summary": {
   "no_memory": {
    "questions": 174,
    "accuracy": 0.46,
    "stale_rate": 0.19,
    "abstain_rate": 0.264,
    "contradiction_rate": 0.552,
    "notes_f1": 0.56,
    "notes_stale_items": 3,
    "tokens_per_task": 1420,
    "final_memory_tokens": 0
   },
   "naive": {
    "questions": 174,
    "accuracy": 0.753,
    "stale_rate": 0.052,
    "abstain_rate": 0.011,
    "contradiction_rate": 0.046,
    "notes_f1": 0.805,
    "notes_stale_items": 9,
    "tokens_per_task": 3563,
    "final_memory_tokens": 4570
   },
   "brain": {
    "questions": 174,
    "accuracy": 0.994,
    "stale_rate": 0.0,
    "abstain_rate": 0.006,
    "contradiction_rate": 0.011,
    "notes_f1": 0.982,
    "notes_stale_items": 0,
    "tokens_per_task": 1653,
    "final_memory_tokens": 1011
   }
  }
 },
 {
  "id": "seed7-live-oracle",
  "label": "seed 7 \u00b7 21d \u00b7 Nemotron-3.5-Lightning-30B-A3B \u00b7 oracle extraction",
  "mode": "live",
  "seed": 7,
  "days": 21,
  "extract": "oracle",
  "product": "Pinwheel",
  "agent_model": "nvidia/Nemotron-3.5-Lightning-30B-A3B",
  "updated": 1792277627.96318,
  "summary": {
   "no_memory": {
    "questions": 172,
    "accuracy": 0.407,
    "stale_rate": 0.221,
    "abstain_rate": 0.262,
    "contradiction_rate": 0.721,
    "notes_f1": 0.378,
    "notes_stale_items": 0,
    "tokens_per_task": 1409,
    "final_memory_tokens": 0
   },
   "naive": {
    "questions": 172,
    "accuracy": 0.727,
    "stale_rate": 0.064,
    "abstain_rate": 0.012,
    "contradiction_rate": 0.047,
    "notes_f1": 0.739,
    "notes_stale_items": 13,
    "tokens_per_task": 3470,
    "final_memory_tokens": 4263
   },
   "brain": {
    "questions": 172,
    "accuracy": 0.988,
    "stale_rate": 0.012,
    "abstain_rate": 0.0,
    "contradiction_rate": 0.023,
    "notes_f1": 1.0,
    "notes_stale_items": 0,
    "tokens_per_task": 1693,
    "final_memory_tokens": 1009
   }
  }
 },
 {
  "id": "seed7-mock-oracle",
  "label": "seed 7 \u00b7 21d \u00b7 mock \u00b7 oracle extraction",
  "mode": "mock",
  "seed": 7,
  "days": 21,
  "extract": "oracle",
  "product": "Pinwheel",
  "agent_model": null,
  "updated": 1792276276.8063135,
  "summary": {
   "no_memory": {
    "questions": 172,
    "accuracy": 0.267,
    "stale_rate": 0.145,
    "abstain_rate": 0.5,
    "contradiction_rate": 0.477,
    "notes_f1": 0.504,
    "notes_stale_items": 9,
    "tokens_per_task": 929,
    "final_memory_tokens": 0
   },
   "naive": {
    "questions": 172,
    "accuracy": 0.779,
    "stale_rate": 0.035,
    "abstain_rate": 0.023,
    "contradiction_rate": 0.0,
    "notes_f1": 0.848,
    "notes_stale_items": 9,
    "tokens_per_task": 2769,
    "final_memory_tokens": 4263
   },
   "brain": {
    "questions": 172,
    "accuracy": 1.0,
    "stale_rate": 0.0,
    "abstain_rate": 0.0,
    "contradiction_rate": 0.0,
    "notes_f1": 1.0,
    "notes_stale_items": 0,
    "tokens_per_task": 1271,
    "final_memory_tokens": 1009
   }
  }
 },
 {
  "id": "seed23-live-oracle",
  "label": "seed 23 \u00b7 21d \u00b7 Nemotron-3.5-Lightning-30B-A3B \u00b7 oracle extraction",
  "mode": "live",
  "seed": 23,
  "days": 21,
  "extract": "oracle",
  "product": "Pinwheel",
  "agent_model": "nvidia/Nemotron-3.5-Lightning-30B-A3B",
  "updated": 1792274570.1699343,
  "summary": {
   "no_memory": {
    "questions": 114,
    "accuracy": 0.325,
    "stale_rate": 0.167,
    "abstain_rate": 0.333,
    "contradiction_rate": 0.561,
    "notes_f1": 0.415,
    "notes_stale_items": 0,
    "tokens_per_task": 1343,
    "final_memory_tokens": 0
   },
   "naive": {
    "questions": 114,
    "accuracy": 0.579,
    "stale_rate": 0.105,
    "abstain_rate": 0.07,
    "contradiction_rate": 0.105,
    "notes_f1": 0.74,
    "notes_stale_items": 12,
    "tokens_per_task": 2840,
    "final_memory_tokens": 3595
   },
   "brain": {
    "questions": 114,
    "accuracy": 0.965,
    "stale_rate": 0.0,
    "abstain_rate": 0.0,
    "contradiction_rate": 0.0,
    "notes_f1": 0.982,
    "notes_stale_items": 0,
    "tokens_per_task": 1291,
    "final_memory_tokens": 719
   }
  }
 }
];
