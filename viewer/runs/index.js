window.RUN_INDEX = [
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
  "updated": 1792274034.3102925,
  "summary": {
   "no_memory": {
    "questions": 114,
    "accuracy": 0.351,
    "stale_rate": 0.211,
    "abstain_rate": 0.351,
    "contradiction_rate": 0.632,
    "notes_f1": 0.237,
    "notes_stale_items": 3,
    "tokens_per_task": 1342,
    "final_memory_tokens": 0
   },
   "naive": {
    "questions": 114,
    "accuracy": 0.658,
    "stale_rate": 0.053,
    "abstain_rate": 0.035,
    "contradiction_rate": 0.053,
    "notes_f1": 0.684,
    "notes_stale_items": 12,
    "tokens_per_task": 2981,
    "final_memory_tokens": 3586
   },
   "brain": {
    "questions": 114,
    "accuracy": 0.947,
    "stale_rate": 0.026,
    "abstain_rate": 0.0,
    "contradiction_rate": 0.053,
    "notes_f1": 0.82,
    "notes_stale_items": 0,
    "tokens_per_task": 1348,
    "final_memory_tokens": 713
   }
  }
 }
];
