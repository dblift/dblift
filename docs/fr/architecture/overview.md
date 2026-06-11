# Vue d'Ensemble de l'Architecture

**Référence Technique pour les Développeurs**

Ce document décrit l'architecture actuelle de DBLift - un outil de migration de base de données supportant PostgreSQL, MySQL, SQL Server, Oracle, DB2, SQLite et Azure Cosmos DB. Il se concentre sur la structure actuelle du système et sur la façon dont les composants interagissent.

## Vue d'Ensemble du Système

### Architecture de Haut Niveau

DBLift suit une architecture en couches où chaque couche a des responsabilités claires :

```
┌─────────────────────────────────────────────────────────┐
│                     Couche CLI                          │
│                  (cli/main.py)                          │
│  - Analyse des arguments                               │
│  - Routage des commandes                               │
│  - Formatage de la sortie                              │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                  Couche Client API                       │
│                  (api/client.py)                        │
│  - DBLiftClient: API d'opérations de haut niveau        │
│  - Chargement de la configuration                       │
│  - Instanciation du fournisseur                         │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                 Moteur de Migration                     │
│            (core/migration/executor/)                  │
│  - MigrationExecutor: Orchestre les opérations          │
│  - Commandes: migrate, undo, baseline, etc.            │
│  - Gestion d'état                                      │
│  - Gestion des scripts                                 │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│             Couche Fournisseur de Base de Données       │
│                 (db/plugins/)                           │
│  - BaseProvider: Interface abstraite                    │
│  - 5 composants par base de données:                    │
│    • ConnectionManager                                 │
│    • QueryExecutor                                     │
│    • SchemaOperations                                  │
│    • LockingManager                                    │
│    • HistoryManager                                    │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│              Couche Base de Données                      │
│  SQLAlchemy: PostgreSQL, MySQL, SQL Server, Oracle, DB2  │
│  Natif: SQLite (Python sqlite3)                         │
│  SDK:  Azure Cosmos DB                                 │
└─────────────────────────────────────────────────────────┘
```

### Principes de Conception Clés

1. **Propriété Explicite** : Le fournisseur possède la connexion, la passe aux composants comme paramètres
2. **Composants Sans État** : QueryExecutor, SchemaOperations, etc. ne stockent pas l'état de connexion
3. **Injection de Dépendances** : Dépendances passées explicitement dans la chaîne d'appels
4. **Abstraction de Base de Données** : Interface commune pour tous les types de bases de données
5. **Modèle Factory** : Création centralisée de composants spécifiques au dialecte

Voir la [documentation complète en anglais](../architecture/overview.md) pour plus de détails.
