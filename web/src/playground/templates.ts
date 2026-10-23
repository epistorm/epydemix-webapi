export type Template = {
  name: string;
  description?: string;
  // Raw JSONC text (comments allowed) shown in the editor when loaded.
  requestText: string;
};

export const TEMPLATES: Template[] = [
  {
    name: 'SIR (US population)',
    description: 'Susceptible-Infected-Recovered on the US population, two months.',
    requestText: `{
  "model": {
    "preset": "SIR",
    "parameters": {
      "R0": 2.5,
      "infectious_period": 10.0
    }
  },
  "population": {
    "name": "United_States"
  },
  "simulation": {
    "start_date": "2024-01-01",
    "end_date": "2024-03-01",
    "Nsim": 10
  },
  "initial_conditions": {
    "method": "percentage",
    "initial_percentages": { "Infected": 0.1 } // 0.1%
  }
}`,
  },
  {
    name: 'SIR (homogeneous population)',
    description: 'Single-group population of 100,000 with a 1x1 contact matrix.',
    requestText: `{
  "model": {
    "preset": "SIR",
    "parameters": {
      "R0": 2.5,
      "infectious_period": 10.0
    }
  },
  "population": {
    "source": "custom",
    "name": "Custom Population 1",
    "age_groups": {
      "A": 338120586
    },
    "contact_matrices": {
      "all": [
        [1.0]
      ]
    }
  },
  "simulation": {
    "start_date": "2024-01-01",
    "end_date": "2024-03-01",
    "Nsim": 5
  },
  "initial_conditions": {
    "method": "percentage",
    "initial_percentages": { "Infected": 0.1 } // 0.1%
  }
}`,
  },
  {
    name: 'SIR with seasonality',
    description: 'SIR on the US population with a Northern-Hemisphere seasonality envelope on transmission_rate.',
    requestText: `{
  "model": {
    "preset": "SIR",
    "parameters": {
      "R0": 2.5,
      "infectious_period": 10.0
    }
  },
  "population": {
    "name": "United_States"
  },
  "simulation": {
    "start_date": "2024-08-01",
    "end_date": "2025-07-31",
    "Nsim": 10
  },
  "initial_conditions": {
    "method": "percentage",
    "initial_percentages": { "Infected": 0.1 } // 0.1%
  },
  // transmission_rate is derived from R0 in parameter_transforms
  "parameter_transforms": [
    {
      "target_parameter": "transmission_rate",
      "method": "balcan",
      "max_date": "2025-01-15",
      "min_date": "2025-07-15",
      "min_value": 0.85
    }
  ]
  // To plot parameter values (e.g. transmission_rate), uncomment the line below:
  // , "output": { "include_parameters": true }
}`,
  },
  {
    name: 'SIR with intervention (scaling)',
    description: 'SIR with a four-week multiplicative reduction of transmission_rate (e.g. an NPI window).',
    requestText: `{
  "model": {
    "preset": "SIR",
    "parameters": {
      "R0": 2.5,
      "infectious_period": 10.0
    }
  },
  "population": {
    "name": "United_States"
  },
  "simulation": {
    "start_date": "2024-01-01",
    "end_date": "2024-05-01",
    "Nsim": 10
  },
  "initial_conditions": {
    "method": "percentage",
    "initial_percentages": { "Infected": 0.1 } // 0.1%
  },
  // Comment this out to compare a scenario without intervention
  "parameter_transforms": [
    {
      "target_parameter": "transmission_rate",
      "method": "scale",
      "start_date": "2024-01-03",
      "end_date": "2024-01-30",
      "factor": 0.2
    }
  ]
  // To plot parameter values (e.g. transmission_rate), uncomment the line below:
  // , "output": { "include_parameters": true }
}`,
  },
  {
    name: 'SEIR',
    description: 'Susceptible-Exposed-Infected-Recovered on the US population.',
    requestText: `{
  "model": {
    "preset": "SEIR",
    "parameters": {
      "R0": 2.5,
      "incubation_period": 5.0,
      "infectious_period": 10.0
    }
  },
  "population": {
    "name": "United_States"
  },
  "simulation": {
    "start_date": "2024-01-01",
    "end_date": "2024-03-01",
    "Nsim": 10
  },
  "initial_conditions": {
    "method": "percentage",
    "initial_percentages": { "Exposed": 0.025, "Infected": 0.025 }
  }
}`,
  },
  {
    name: 'SIS',
    description: 'Susceptible-Infected-Susceptible (no permanent recovery) on the US population.',
    requestText: `{
  "model": {
    "preset": "SIS",
    "parameters": {
      "R0": 2.5,
      "infectious_period": 10.0
    }
  },
  "population": {
    "name": "United_States"
  },
  "simulation": {
    "start_date": "2024-01-01",
    "end_date": "2024-06-01",
    "Nsim": 10
  },
  "initial_conditions": {
    "method": "percentage",
    "initial_percentages": { "Infected": 0.1 } // 0.1%
  }
}`,
  },
  {
    name: 'V-SEIR (flat-count vaccination)',
    description: 'V-SEIR on the US population with a flat-count vaccination campaign.',
    requestText: `{
  "model": {
    "preset": "V-SEIR",
    "parameters": {
      "R0": 2.5,
      "incubation_period": 3.0,
      "infectious_period": 2.5,
      "VE_S": 0.7
    }
  },
  "population": {
    "name": "United_States"
  },
  "simulation": {
    "start_date": "2025-01-01",
    "end_date": "2025-06-30",
    "Nsim": 10
  },
  "initial_conditions": {
    "method": "percentage",
    "initial_percentages": { "Exposed": 0.025, "Infected": 0.025 }
  },
  "vaccination": {
    "campaigns": [
      {
        "start_date": "2025-02-01",
        "end_date": "2025-04-30",
        "rollout": {
          "type": "flat_count",
          "daily_doses": 100000
        }
      }
    ]
  }
}`,
  },
  {
    name: 'V-SEIHR (flat-count vaccination)',
    description: 'V-SEIHR on the US population with a flat-count vaccination campaign.',
    requestText: `{
  "model": {
    "preset": "V-SEIHR",
    "parameters": {
      "R0": 2.5,
      "incubation_period": 3.0,
      "infectious_period": 2.5,
      "hosp_duration": 5.0,
      "hosp_proportion": [0.002, 0.005, 0.015, 0.05, 0.18],
      "VE_S": 0.7,
      "VE_H": 0.85
    }
  },
  "population": {
    "name": "United_States"
  },
  "simulation": {
    "start_date": "2025-01-01",
    "end_date": "2025-06-30",
    "Nsim": 10
  },
  "initial_conditions": {
    "method": "percentage",
    "initial_percentages": { "Exposed": 0.025, "Infected": 0.025 }
  },
  "vaccination": {
    "campaigns": [
      {
        "start_date": "2025-02-01",
        "end_date": "2025-04-30",
        "rollout": {
          "type": "flat_count",
          "daily_doses": 100000
        }
      }
    ]
  }
}`,
  },
  {
    name: 'V-SEIHR (fixed-rate vaccination)',
    description: 'V-SEIHR on the US population with a fixed-rate vaccination campaign (per-day hazard).',
    requestText: `{
  "model": {
    "preset": "V-SEIHR",
    "parameters": {
      "R0": 2.5,
      "incubation_period": 3.0,
      "infectious_period": 2.5,
      "hosp_duration": 5.0,
      "hosp_proportion": [0.002, 0.005, 0.015, 0.05, 0.18],
      "VE_S": 0.7,
      "VE_H": 0.85
    }
  },
  "population": {
    "name": "United_States"
  },
  "simulation": {
    "start_date": "2025-01-01",
    "end_date": "2025-06-30",
    "Nsim": 10
  },
  "initial_conditions": {
    "method": "percentage",
    "initial_percentages": { "Exposed": 0.025, "Infected": 0.025 }
  },
  "vaccination": {
    "campaigns": [
      {
        "start_date": "2025-02-01",
        "end_date": "2025-04-30",
        "rollout": {
          "type": "fixed_rate",
          "rate": 0.005
        }
      }
    ]
  }
}`,
  },
  {
    name: 'V-SEIHR (seasonality+vaccination)',
    description: 'Year-long V-SEIHR run with seasonality and a flat-count campaign.',
    requestText: `{
  "model": {
    "preset": "V-SEIHR",
    "parameters": {
      "R0": 2.5,
      "incubation_period": 3.0,
      "infectious_period": 2.5,
      "hosp_duration": 5.0,
      "hosp_proportion": [0.002, 0.005, 0.015, 0.05, 0.18],
      "VE_S": 0.7,
      "VE_H": 0.85
    }
  },
  "population": {
    "name": "United_States"
  },
  "simulation": {
    "start_date": "2025-08-01",
    "end_date": "2026-07-31",
    "Nsim": 10
  },
  "initial_conditions": {
    "method": "percentage",
    "initial_percentages": { "Exposed": 0.025, "Infected": 0.025 }
  },
  "parameter_transforms": [
    {
      "target_parameter": "transmission_rate",
      "method": "balcan",
      "max_date": "2026-01-15",
      "min_date": "2026-07-15",
      "min_value": 0.85
    }
  ],
  "vaccination": {
    "campaigns": [
      {
        "start_date": "2025-10-15",
        "end_date": "2025-12-31",
        "rollout": {
          "type": "flat_count",
          "daily_doses": 100000
        }
      }
    ]
  }
  // To plot parameter values (e.g. transmission_rate), uncomment the line below:
  // , "output": { "include_parameters": true }
}`,
  },
];
