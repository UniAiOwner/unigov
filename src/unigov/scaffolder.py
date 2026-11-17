import os
import json
from pathlib import Path

scaffolder_path = Path("/media/uniai/UniAi/PROJECTS_MIGRATED/unigov/src/unigov/scaffolder.py")

DIMENSION_METADATA = [
    {
        "index": 1,
        "folder_name": "01_VISION_AND_CONSTRAINTS",
        "filename": "01_VISION_AND_CONSTRAINTS.md",
        "title": "Vision, Personas & Constitutional Hard Constraints",
        "layer": "LAYER_1_DOMAIN",
        "description": "Core problem statement, target personas, non-goals, and non-negotiable architectural laws.",
        "invariants": [
            {
                "id": "INV-LAW-000",
                "layer": "LAYER_1_DOMAIN",
                "title": "Constitutional Zero-Shortcut Rule",
                "rule_type": "FORBIDDEN_TOKENS",
                "file_patterns": ["**/*.kt", "**/*.ts", "**/*.py"],
                "params": {"forbidden_tokens": ["@Suppress(\"ALL\")", "@Suppress(\"UNCHECKED_CAST\")"]},
                "enforcement": "BLOCK_BUILD",
            }
        ],
        "sub_documents": [
            {
                "filename": "01_Core_Vision_and_Product_Philosophy.md",
                "title": "Core Vision, Operating Philosophy & Continuity Layer",
                "description": "Fundamental product purpose: converting fragmented operational memory into an enduring digital customer lifecycle where the customer is the continuity layer.",
                "invariants": []
            },
            {
                "filename": "02_User_Personas_and_Shopfront_Reality.md",
                "title": "User Personas, Shopfront Realities & Ground Constraints",
                "description": "Comprehensive persona mapping: rural/semi-urban frontline operators, citizens, elderly, and rural customers with high operational speed constraints.",
                "invariants": []
            },
            {
                "filename": "03_Constitutional_Invariants_and_Laws.md",
                "title": "Constitutional Laws, Strict Engineering Rules & Invariants",
                "description": "Constitutional laws: Law-000 zero-shortcut rule, zero @Suppress annotations, and statutory compliance bounds.",
                "invariants": [
                    {
                        "id": "INV-LAW-000",
                        "layer": "LAYER_1_DOMAIN",
                        "title": "Constitutional Zero-Shortcut Rule",
                        "rule_type": "FORBIDDEN_TOKENS",
                        "file_patterns": ["**/*.kt", "**/*.ts", "**/*.py"],
                        "params": {"forbidden_tokens": ["@Suppress(\"ALL\")", "@Suppress(\"UNCHECKED_CAST\")"]},
                        "enforcement": "BLOCK_BUILD",
                    }
                ]
            },
            {
                "filename": "04_System_Boundaries_and_Non_Goals.md",
                "title": "System Boundaries, Scope Limits & Explicit Non-Goals",
                "description": "Explicit product boundaries: what the software does, what is deferred to subsequent milestones, and strict non-goals.",
                "invariants": []
            }
        ]
    },
    {
        "index": 2,
        "folder_name": "02_DOMAIN_RULES_AND_FSM",
        "filename": "02_DOMAIN_RULES_AND_FSM.md",
        "title": "Domain Rules, Financial Math & Finite State Machines",
        "layer": "LAYER_1_DOMAIN",
        "description": "Strict business logic, tax calculation invariants, integer math, and entity FSM transitions.",
        "invariants": [
            {
                "id": "INV-FIN-001",
                "layer": "LAYER_1_DOMAIN",
                "title": "Law ACC-001 Zero Float Financial Math",
                "rule_type": "FORBIDDEN_TOKENS",
                "file_patterns": ["**/billing/**", "**/ledger/**", "**/domain/inventory/**", "**/pos/**"],
                "params": {"forbidden_tokens": ["Float", "Double", "BigDecimal.toFloat", "0.18f"]},
                "enforcement": "BLOCK_BUILD",
            }
        ],
        "sub_documents": [
            {
                "filename": "01_Service_Catalog_and_Taxonomy.md",
                "title": "Service Catalog, Taxonomy & Category Hierarchy",
                "description": "Catalog categorization, government vs commercial service distinctions, prerequisite document rules, and delivery turnaround targets.",
                "invariants": []
            },
            {
                "filename": "02_Service_Lifecycle_FSM_State_Machine.md",
                "title": "Multi-Stage Service Lifecycle Finite State Machine (FSM)",
                "description": "Deterministic state transitions (Intake, Processing, Ready, Delivered, Completed, Cancelled, Rejected) with strict validation guards.",
                "invariants": []
            },
            {
                "filename": "03_Split_Pricing_and_Revenue_Math.md",
                "title": "Split Pricing Model, Fee Mathematics & Law ACC-001 Invariants",
                "description": "Integer Paise accounting for government portal fees, operator convenience charges, taxes, discounts, and strict zero-float math.",
                "invariants": [
                    {
                        "id": "INV-FIN-001",
                        "layer": "LAYER_1_DOMAIN",
                        "title": "Law ACC-001 Zero Float Financial Math",
                        "rule_type": "FORBIDDEN_TOKENS",
                        "file_patterns": ["**/billing/**", "**/ledger/**", "**/domain/inventory/**", "**/pos/**"],
                        "params": {"forbidden_tokens": ["Float", "Double", "BigDecimal.toFloat", "0.18f"]},
                        "enforcement": "BLOCK_BUILD",
                    }
                ]
            },
            {
                "filename": "04_Khata_Ledger_and_FIFO_Debt_Settlement.md",
                "title": "Customer Khata Ledger, Outstanding Dues & FIFO Debt Settlement",
                "description": "Customer balance management, partial advance payments, credit limits, and First-In-First-Out due debt allocation.",
                "invariants": []
            }
        ]
    },
    {
        "index": 3,
        "folder_name": "03_USER_WORKFLOWS_AND_CHAOS",
        "filename": "03_USER_WORKFLOWS_AND_CHAOS.md",
        "title": "User Workflows, Sad Paths & Chaos Recovery",
        "layer": "LAYER_1_DOMAIN",
        "description": "Happy user journeys mapped alongside mid-transaction app kills, rapid double-taps, and low battery.",
        "invariants": [],
        "sub_documents": [
            {
                "filename": "01_Frontline_Happy_Paths.md",
                "title": "Frontline Operator Happy Path Workflows",
                "description": "End-to-end customer journeys: new citizen intake, returning citizen instant retrieval, and multi-service order creation.",
                "invariants": []
            },
            {
                "filename": "02_Document_Verification_Intake_Flow.md",
                "title": "Document Verification & Human-in-the-Loop Review Gate",
                "description": "Camera capture, automated quality evaluation, OCR candidate presentation, side-by-side verification, and explicit confirmation.",
                "invariants": []
            },
            {
                "filename": "03_Chaos_Engineering_and_Sad_Paths.md",
                "title": "Sad Paths, Chaos Engineering & Mid-Transaction Recovery",
                "description": "Handling unexpected real-world faults: mid-payment crash, camera hardware disconnection, network dropout, low battery, and rapid double-taps.",
                "invariants": []
            }
        ]
    },
    {
        "index": 4,
        "folder_name": "04_DATA_SCHEMA_AND_MIGRATIONS",
        "filename": "04_DATA_SCHEMA_AND_MIGRATIONS.md",
        "title": "Data Schema, Indexes & Zero-Downtime Migrations",
        "layer": "LAYER_2_DATA",
        "description": "Normalized SQL/Room tables, foreign keys, compound indexes, and tested schema migration plans.",
        "invariants": [],
        "sub_documents": [
            {
                "filename": "01_Room_Database_Schema_and_DDL.md",
                "title": "Room Database Relational Schema & SQL DDL Specification",
                "description": "Complete schema definitions for all core entities: customers, documents, catalog, transactions, ledger, reminders, reconciliation, and audit.",
                "invariants": []
            },
            {
                "filename": "02_SQLCipher_256Bit_Encryption_Spec.md",
                "title": "SQLCipher 256-Bit AES Database Encryption Specification",
                "description": "Page-level database encryption, passphrase derivation via Android Keystore, SQLCipher SupportFactory binding, and memory scrubbing.",
                "invariants": []
            },
            {
                "filename": "03_Entity_Relationships_and_Indexes.md",
                "title": "Entity Relationships, Foreign Key Cascades & Query Indexes",
                "description": "Entity ER relationships, foreign key constraints, composite query indexes for sub-50ms search, and soft-deletion flags.",
                "invariants": []
            },
            {
                "filename": "04_Zero_Downtime_Migrations_and_Testing.md",
                "title": "Zero-Downtime Schema Migrations & Room MigrationTestHelper",
                "description": "Automated schema migration strategy (MIGRATION_1_2, MIGRATION_2_3), schema JSON export, and MigrationTestHelper test harnesses.",
                "invariants": []
            }
        ]
    },
    {
        "index": 5,
        "folder_name": "05_OFFLINE_SYNC_AND_IDEMPOTENCY",
        "filename": "05_OFFLINE_SYNC_AND_IDEMPOTENCY.md",
        "title": "Offline Sync, Idempotency & Conflict Resolution",
        "layer": "LAYER_2_DATA",
        "description": "Client-generated UUID idempotency keys, append-only event ledgers, and background sync workers.",
        "invariants": [
            {
                "id": "INV-SYNC-001",
                "layer": "LAYER_2_DATA",
                "title": "Mandatory Client Idempotency Key",
                "rule_type": "REQUIRED_COLUMNS",
                "file_patterns": ["**/data/local/entity/**", "**/models/**"],
                "params": {"required_columns": ["idempotency_key", "sync_status"]},
                "enforcement": "BLOCK_BUILD",
            }
        ],
        "sub_documents": [
            {
                "filename": "01_Local_Master_Persistence_Model.md",
                "title": "Local-First Master Persistence Model",
                "description": "Local Room database as the primary source of truth, guaranteeing zero latency and complete front-desk operational autonomy without internet.",
                "invariants": []
            },
            {
                "filename": "02_Outbox_Pattern_and_Sync_Queue.md",
                "title": "Transactional Outbox Pattern & Background Sync Engine",
                "description": "Transactional mutation outbox, exponential backoff retries, network change broadcast receivers, and background synchronization workers.",
                "invariants": [
                    {
                        "id": "INV-SYNC-001",
                        "layer": "LAYER_2_DATA",
                        "title": "Mandatory Client Idempotency Key",
                        "rule_type": "REQUIRED_COLUMNS",
                        "file_patterns": ["**/data/local/entity/**", "**/models/**"],
                        "params": {"required_columns": ["idempotency_key", "sync_status"]},
                        "enforcement": "BLOCK_BUILD",
                    }
                ]
            },
            {
                "filename": "03_Idempotency_Keys_and_Conflict_Resolution.md",
                "title": "Client Idempotency Keys, Vector Clocks & Conflict Policies",
                "description": "Client-side UUIDv7 key generation, deduplication guarantees, Last-Write-Wins timestamps, and manual operator reconciliation queues.",
                "invariants": []
            }
        ]
    },
    {
        "index": 6,
        "folder_name": "06_ARCHITECTURE_AND_ADRS",
        "filename": "06_ARCHITECTURE_AND_ADRS.md",
        "title": "Clean Architecture Boundaries & ADR Ledger",
        "layer": "LAYER_2_DATA",
        "description": "Strict module boundaries (:core:domain, :core:data, :feature:*), DI graph, and Architecture Decision Records.",
        "invariants": [],
        "sub_documents": [
            {
                "filename": "01_Clean_Architecture_Multi_Module_DAG.md",
                "title": "Multi-Module Clean Architecture Directed Acyclic Graph (DAG)",
                "description": "Module boundary contracts: :core:security, :data:local, :domain, :engine:ai, :engine:hardware, :presentation, and dependency rules.",
                "invariants": []
            },
            {
                "filename": "02_Dependency_Injection_Hilt_Contracts.md",
                "title": "Dagger-Hilt Dependency Injection Scopes & Lifetime Contracts",
                "description": "SingletonComponent, ViewModelComponent scopes, CoroutineDispatcher qualifiers (@IoDispatcher, @DefaultDispatcher), and interface bindings.",
                "invariants": []
            },
            {
                "filename": "03_Architecture_Decision_Records_ADR_Ledger.md",
                "title": "Architecture Decision Records (ADR) Ledger",
                "description": "Immutable architectural records: ADR-001 (Integer Paise), ADR-002 (SQLCipher), ADR-003 (Salted Hash), ADR-004 (ESC/POS SPP), ADR-005 (CameraX ML Kit).",
                "invariants": []
            }
        ]
    },
    {
        "index": 7,
        "folder_name": "07_DESIGN_SYSTEM_AND_5_STATES",
        "filename": "07_DESIGN_SYSTEM_AND_5_STATES.md",
        "title": "Design System Tokens & 5 Mandatory UI States",
        "layer": "LAYER_3_SURFACES",
        "description": "Color/typography tokens and strict enforcement of 5 UI states: Loading, Empty, Error, Offline, Populated.",
        "invariants": [
            {
                "id": "INV-UI-001",
                "layer": "LAYER_3_SURFACES",
                "title": "Mandatory 5-State Screen Handling",
                "rule_type": "MANDATORY_UI_STATES",
                "file_patterns": ["**/ui/**/*.kt", "**/components/**/*.kt", "**/screens/**/*.tsx"],
                "params": {"required_states": ["Loading", "Empty", "Error", "Offline", "Populated"]},
                "enforcement": "WARN",
            }
        ],
        "sub_documents": [
            {
                "filename": "01_Material3_Design_Tokens_and_Theme.md",
                "title": "Material 3 Design Tokens, Color Palettes & Typography",
                "description": "Design Tokens Format (DTCG), light/dark luminance surfaces, high-contrast text ratios (WCAG AAA), and custom typography scales.",
                "invariants": []
            },
            {
                "filename": "02_Five_Mandatory_UI_States_Specification.md",
                "title": "Five Mandatory UI States Specification across All Screens",
                "description": "Enforcement of 5 explicit states (Loading, Empty, Content, Error, Offline) across every screen composable to eliminate blank/frozen UI states.",
                "invariants": [
                    {
                        "id": "INV-UI-001",
                        "layer": "LAYER_3_SURFACES",
                        "title": "Mandatory 5-State Screen Handling",
                        "rule_type": "MANDATORY_UI_STATES",
                        "file_patterns": ["**/ui/**/*.kt", "**/components/**/*.kt", "**/screens/**/*.tsx"],
                        "params": {"required_states": ["Loading", "Empty", "Error", "Offline", "Populated"]},
                        "enforcement": "WARN",
                    }
                ]
            },
            {
                "filename": "03_Ergonomics_and_Adaptive_Layouts.md",
                "title": "Frontline Thumb-Zone Ergonomics & Multi-Device Adaptive Layouts",
                "description": "Touch target minimums (48x48dp), bottom navigation thumb-zone placement, tablet dual-pane master-detail, and foldable screen support.",
                "invariants": []
            }
        ]
    },
    {
        "index": 8,
        "folder_name": "08_HARDWARE_PERIPHERALS_AND_OS",
        "filename": "08_HARDWARE_PERIPHERALS_AND_OS.md",
        "title": "Hardware Peripherals, Drivers & OS Contracts",
        "layer": "LAYER_3_SURFACES",
        "description": "CameraX scanner latency, raw ESC/POS thermal printer byte protocols, Bluetooth queues, and OS permissions.",
        "invariants": [],
        "sub_documents": [
            {
                "filename": "01_CameraX_Vision_Pipeline_Spec.md",
                "title": "CameraX ImageAnalysis Pipeline & Hardware Scanner Spec",
                "description": "CameraX lifecycle-aware preview, 1080p ImageAnalysis stream, dynamic reticle UI overlay, torch toggle, and auto-focus locks.",
                "invariants": []
            },
            {
                "filename": "02_Bluetooth_ESC_POS_Thermal_Printer_Driver.md",
                "title": "Native Bluetooth ESC/POS 58mm/80mm Thermal Printer Driver",
                "description": "RFCOMM SPP Bluetooth socket streaming, ESC/POS byte protocol builder, line wrapping, alignment codes, and printer auto-reconnection.",
                "invariants": []
            },
            {
                "filename": "03_Vector_PDF_and_Dynamic_UPI_QR_Engine.md",
                "title": "Android Vector PdfDocument Receipt Engine & Dynamic UPI QR",
                "description": "Standard A4 / slip vector PDF generation, customer digital receipt sharing, and high-contrast NPCI dynamic UPI QR code generator.",
                "invariants": []
            }
        ]
    },
    {
        "index": 9,
        "folder_name": "09_SECURITY_RBAC_AND_KEYSTORE",
        "filename": "09_SECURITY_RBAC_AND_KEYSTORE.md",
        "title": "Security, RBAC & Android Keystore Encryption",
        "layer": "LAYER_4_SECURITY",
        "description": "Hardware-backed Keystore AES-256-GCM, salted password hashing (Argon2id/PBKDF2), and strict least-privilege RBAC roles.",
        "invariants": [
            {
                "id": "INV-SEC-001",
                "layer": "LAYER_4_SECURITY",
                "title": "Zero Hardcoded Secret Tokens",
                "rule_type": "FORBIDDEN_TOKENS",
                "file_patterns": ["**/*.kt", "**/*.ts", "**/*.py"],
                "params": {"forbidden_patterns": ["AIza[0-9A-Za-z-_]{35}", "ghp_[0-9A-Za-z]{36}"]},
                "enforcement": "BLOCK_BUILD",
            }
        ],
        "sub_documents": [
            {
                "filename": "01_Android_Keystore_Hardware_TEE_Security.md",
                "title": "Android Keystore Hardware TEE/StrongBox Cryptographic Engine",
                "description": "Master key generation in hardware-backed TEE, AES-256-GCM IV prefixing, key attestation, and streaming file vault encryption.",
                "invariants": []
            },
            {
                "filename": "02_UIDAI_and_Aadhaar_Act_Compliance_Spec.md",
                "title": "UIDAI Regulations & Aadhaar Act 2016 Statutory Compliance",
                "description": "Absolute prohibition of raw 12-digit Aadhaar storage; mandatory 8-digit client-side masking (XXXX-XXXX-1234), and salted SHA-256 deduplication.",
                "invariants": []
            },
            {
                "filename": "03_DPDP_Act_2023_and_RAM_Memory_Scrubbing.md",
                "title": "Digital Personal Data Protection (DPDP) Act 2023 & RAM Scrubbing",
                "description": "Explicit purpose limitation, citizen intake consent, immediate memory scrubbing of OCR buffers via Arrays.fill('\\\\0'), and right to erasure.",
                "invariants": [
                    {
                        "id": "INV-SEC-001",
                        "layer": "LAYER_4_SECURITY",
                        "title": "Zero Hardcoded Secret Tokens",
                        "rule_type": "FORBIDDEN_TOKENS",
                        "file_patterns": ["**/*.kt", "**/*.ts", "**/*.py"],
                        "params": {"forbidden_patterns": ["AIza[0-9A-Za-z-_]{35}", "ghp_[0-9A-Za-z]{36}"]},
                        "enforcement": "BLOCK_BUILD",
                    }
                ]
            },
            {
                "filename": "04_Role_Based_Access_Control_RBAC.md",
                "title": "Role-Based Access Control (RBAC) & Sensitive Action Gates",
                "description": "Owner, Operator, and Auditor roles; elevated re-authentication for sensitive document reveal, payment adjustments, and data export.",
                "invariants": []
            }
        ]
    },
    {
        "index": 10,
        "folder_name": "10_TEST_PYRAMID_AND_SLAS",
        "filename": "10_TEST_PYRAMID_AND_SLAS.md",
        "title": "Test Strategy, Performance Budgets & SLAs",
        "layer": "LAYER_4_SECURITY",
        "description": "Cold start SLAs (< 800ms), 60/120fps UI render budgets, Room migration tests, and E2E verification test suites.",
        "invariants": [],
        "sub_documents": [
            {
                "filename": "01_Test_Strategy_and_Pyramid.md",
                "title": "Automated Test Strategy & Test Pyramid Architecture",
                "description": "Testing distribution: 70% Unit tests (domain & state machines), 20% Integration tests (Room DAOs, hardware mocks), and 10% E2E UI tests.",
                "invariants": []
            },
            {
                "filename": "02_Unit_and_Turbine_StateFlow_Test_Specs.md",
                "title": "JUnit 5, MockK Repositories & Turbine StateFlow Test Specs",
                "description": "Unit test specifications for domain interactors, mock repository testing, and Turbine coroutine StateFlow event assertions.",
                "invariants": []
            },
            {
                "filename": "03_Performance_Budgets_and_SLAs.md",
                "title": "Frontline Performance Budgets & Non-Functional SLAs",
                "description": "Deterministic SLAs: sub-50ms customer search latency, sub-800ms CameraX OCR processing, 60fps UI rendering, cold start <= 800ms.",
                "invariants": []
            }
        ]
    },
    {
        "index": 11,
        "folder_name": "11_OBSERVABILITY_AND_ROLLOUT",
        "filename": "11_OBSERVABILITY_AND_ROLLOUT.md",
        "title": "Observability, Telemetry & Staged Rollout",
        "layer": "LAYER_4_SECURITY",
        "description": "Structured breadcrumb crash logging (zero PII leaks), local diagnostic log bundles, and staged feature rollout flags.",
        "invariants": [],
        "sub_documents": [
            {
                "filename": "01_Structured_Local_Logging_and_Audit.md",
                "title": "Structured Local Diagnostic Logging & PII Leak Defense",
                "description": "Logback Android integration, contextual breadcrumbs, error severity categories, and absolute prohibition of PII in application logs.",
                "invariants": []
            },
            {
                "filename": "02_Inotify_Filesystem_Sentinel_Spec.md",
                "title": "UniGov Inotify Filesystem Sentinel & Runtime Watchdog",
                "description": "Real-time file mutation tracking, continuous architectural drift monitoring, staged secret detection, and automated backup hooks.",
                "invariants": []
            },
            {
                "filename": "03_Safe_Staged_Rollout_and_Feature_Flags.md",
                "title": "Safe Staged Rollout, Local Feature Flags & Version Compatibility",
                "description": "Local feature flags, dark launching new service workflows, backward-compatible API contracts, and graceful rollback procedures.",
                "invariants": []
            }
        ]
    },
    {
        "index": 12,
        "folder_name": "12_ON_DEVICE_AI_AND_SLM_LIMITS",
        "filename": "12_ON_DEVICE_AI_AND_SLM_LIMITS.md",
        "title": "On-Device SLM Intelligence & Memory Ceilings",
        "layer": "LAYER_5_INTELLIGENCE",
        "description": "Quantized SLM models, maximum RAM ceiling (<= 350MB), inference latency SLAs (< 400ms), and low-battery safety switches.",
        "invariants": [
            {
                "id": "INV-AI-001",
                "layer": "LAYER_5_INTELLIGENCE",
                "title": "On-Device AI Memory & Battery Guardrail",
                "rule_type": "LATENCY_BUDGET",
                "file_patterns": ["**/cortex/**", "**/ai/**", "**/slm/**"],
                "params": {"max_ram_mb": 350, "max_latency_ms": 400},
                "enforcement": "WARN",
            }
        ],
        "sub_documents": [
            {
                "filename": "01_Frame_Quality_Pre_Flight_Gate.md",
                "title": "Frame Quality Pre-Flight Gate (Laplacian Blur & Glare)",
                "description": "Laplacian variance blur evaluation, luminance clipping (glare detection), perspective skew estimation, and operator guidance prompts.",
                "invariants": []
            },
            {
                "filename": "02_Document_Taxonomy_Classifier.md",
                "title": "Heuristic Document Taxonomy Classifier",
                "description": "Multi-taxonomy document classification: Aadhaar (front/back), PAN card, Voter ID (EPIC), Ration Card, Domicile, and Income certificates.",
                "invariants": []
            },
            {
                "filename": "03_Geometric_Entity_Parsers.md",
                "title": "Geometric Entity Extractors & Regex Parsers",
                "description": "Deterministic entity extraction: full name, date of birth, gender, care-of, document ID number, address, and bounding box scoring.",
                "invariants": []
            },
            {
                "filename": "04_Memory_and_Compute_Ceilings.md",
                "title": "On-Device Memory Limits, Bitmap Recycling & Compute Ceilings",
                "description": "Strict RAM ceiling (<= 120MB for image pipelines), automatic Bitmap recycling, non-blocking coroutine dispatching, and low-battery pauses.",
                "invariants": [
                    {
                        "id": "INV-AI-001",
                        "layer": "LAYER_5_INTELLIGENCE",
                        "title": "On-Device AI Memory & Battery Guardrail",
                        "rule_type": "LATENCY_BUDGET",
                        "file_patterns": ["**/cortex/**", "**/ai/**", "**/slm/**"],
                        "params": {"max_ram_mb": 350, "max_latency_ms": 400},
                        "enforcement": "WARN",
                    }
                ]
            }
        ]
    },
    {
        "index": 13,
        "folder_name": "13_TAMPER_PROOF_AUDIT_LEDGER",
        "filename": "13_TAMPER_PROOF_AUDIT_LEDGER.md",
        "title": "Cryptographic Audit Ledger & Fraud Prevention",
        "layer": "LAYER_5_INTELLIGENCE",
        "description": "Merkle-tree hash chained audit entries for every transaction, discount, or cancellation to detect employee theft.",
        "invariants": [],
        "sub_documents": [
            {
                "filename": "01_Merkle_Hash_Chaining_Architecture.md",
                "title": "Merkle Hash-Chained Audit Ledger Architecture",
                "description": "Immutable cryptographic chaining: current_hash = SHA256(prev_hash + actor_id + timestamp + payload_json), tamper-evident validation.",
                "invariants": []
            },
            {
                "filename": "02_Audit_Event_Taxonomy_and_Triggers.md",
                "title": "Audit Event Taxonomy & Operational Mutation Triggers",
                "description": "Audit event catalog: record creation, fee adjustments, service status transitions, document reveal events, and data export attempts.",
                "invariants": []
            },
            {
                "filename": "03_Cryptographic_Integrity_Verification.md",
                "title": "Cryptographic Ledger Integrity Verification & Fraud Detection",
                "description": "Deterministic audit ledger verification algorithm, broken chain detection, unauthorized database mutation alerts, and compliance reports.",
                "invariants": []
            }
        ]
    },
    {
        "index": 14,
        "folder_name": "14_DISASTER_RECOVERY_60S_SWAP",
        "filename": "14_DISASTER_RECOVERY_60S_SWAP.md",
        "title": "60-Second Disaster Recovery & Hardware Swap Protocol",
        "layer": "LAYER_5_INTELLIGENCE",
        "description": "Encrypted P2P local Wi-Fi / BLE hot-standby sync, allowing instant replacement and recovery if a phone breaks.",
        "invariants": [],
        "sub_documents": [
            {
                "filename": "01_SQLite_WAL_Encrypted_Snapshot_Backup.md",
                "title": "SQLite WAL Encrypted Snapshot & Backup Strategy",
                "description": "Atomic online database snapshots via VACUUM INTO, WAL checkpointing, client-side AES-256 backup encryption, and local storage targets.",
                "invariants": []
            },
            {
                "filename": "02_Sixty_Second_Hardware_Swap_Protocol.md",
                "title": "Sixty-Second Hardware Device Replacement Protocol",
                "description": "Shopfront emergency device replacement: quick app install, QR key restore, encrypted backup ingestion, and zero data loss resumption.",
                "invariants": []
            }
        ]
    },
    {
        "index": 15,
        "folder_name": "15_SELF_HEALING_AND_RESILIENCE",
        "filename": "15_SELF_HEALING_AND_RESILIENCE.md",
        "title": "Self-Healing App Architecture & Safe Mode",
        "layer": "LAYER_5_INTELLIGENCE",
        "description": "Automatic migration rollback, corrupted transaction isolation (quarantine), and non-fatal fallback recovery.",
        "invariants": [],
        "sub_documents": [
            {
                "filename": "01_Database_Corruption_Auto_Recovery.md",
                "title": "Database Corruption Detection & Automated Recovery",
                "description": "Automatic PRAGMA integrity_check on boot, corrupted page quarantine, salvage JSON dumps, and safe database rebuilding.",
                "invariants": []
            },
            {
                "filename": "02_Safe_Mode_Boot_and_Rollback.md",
                "title": "Safe Mode Boot Loop Protection & Config Rollback",
                "description": "Crash loop detection (> 3 crashes in 60s), Safe Mode boot with diagnostic HUD, feature flag disabling, and config rollback.",
                "invariants": []
            },
            {
                "filename": "03_Peripheral_Circuit_Breakers.md",
                "title": "Peripheral Circuit Breakers & Hardware Degradation Handlers",
                "description": "Circuit breakers for Bluetooth thermal printer (timeout backoff, queue buffering) and camera sensors (manual file upload fallback).",
                "invariants": []
            }
        ]
    }
]


def generate_scaffold_markdown(meta: dict, project_name: str, sub_doc: dict = None) -> str:
    title = sub_doc["title"] if sub_doc else meta["title"]
    filename = sub_doc["filename"] if sub_doc else meta.get("filename", "SPEC.md")
    description = sub_doc["description"] if sub_doc else meta["description"]
    invariants = sub_doc.get("invariants", []) if sub_doc else meta.get("invariants", [])

    invariants_blocks = ""
    for inv in invariants:
        invariants_blocks += f"""
<!-- UNIGOV_INVARIANT_START -->
{json.dumps(inv, indent=2)}
<!-- UNIGOV_INVARIANT_END -->
"""

    return f"""# 📑 {filename} — {title}
**Project:** {project_name}  
**Dimension:** `{meta.get('folder_name', meta['title'])}`  
**Architectural Layer:** `{meta['layer']}`  
**Standard Version:** 2026 SOTA Modular Production Specification

---

## 🎯 1. Overview & Objective
{description}

---

## 🔒 2. Architectural Invariants (Machine-Executable Contracts)
The following invariant blocks are machine-compiled and enforced by `unigov` during build and commit phases:
{invariants_blocks or "*No automated machine invariants currently active for this section.*"}

---

## 📝 3. Detailed Specification & Production Implementation Rules
*(Fill out specific project domain schemas, FSM state tables, or hardware contracts below)*

### Core Invariants:
1. All changes must pass verified CI/CD gates before merging.
2. Zero shortcut implementations (Law-000).
3. Zero silent error suppression.

---
*Created automatically by UniGov v0.6.0 Modular Scaffolder*
"""


def scaffold_documentation_suite(
    target_dir: Path, 
    project_name: str = "Enterprise Mobile OS", 
    overwrite: bool = False,
    modular: bool = True
) -> list:
    """Generates the full 15-dimension architectural documentation suite.
    
    When modular=True (default), generates 15 dedicated folders with deep sub-documents.
    When modular=False, generates 15 flat files for backwards compatibility.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    created_files = []

    for meta in DIMENSION_METADATA:
        if modular and "folder_name" in meta:
            folder_path = target_dir / meta["folder_name"]
            folder_path.mkdir(parents=True, exist_ok=True)
            
            # 1. Create INDEX.md inside folder
            index_path = folder_path / "INDEX.md"
            if not index_path.exists() or overwrite:
                sub_docs_list = "\n".join(f"- [{sd['filename']}](./{sd['filename']}): {sd['title']}" for sd in meta.get("sub_documents", []))
                index_content = f"""# 📁 {meta['folder_name']} — {meta['title']}
**Project:** {project_name}  
**Architectural Layer:** `{meta['layer']}`  
**Dimension Overview:** {meta['description']}

---

### 📑 Modular Specifications in this Dimension:
{sub_docs_list}

---
*UniGov v0.6.0 Modular Architecture Index*
"""
                index_path.write_text(index_content, encoding="utf-8")
                created_files.append(index_path)

            # 2. Create sub-documents inside folder
            for sub_doc in meta.get("sub_documents", []):
                file_path = folder_path / sub_doc["filename"]
                if file_path.exists() and not overwrite:
                    continue
                content = generate_scaffold_markdown(meta, project_name, sub_doc=sub_doc)
                file_path.write_text(content, encoding="utf-8")
                created_files.append(file_path)
        else:
            file_path = target_dir / meta["filename"]
            if file_path.exists() and not overwrite:
                continue
            content = generate_scaffold_markdown(meta, project_name)
            file_path.write_text(content, encoding="utf-8")
            created_files.append(file_path)

    return created_files
