# Documentation DBLift

<p align="center">
  <img src="../../logo/dblift_logo.png" width="600" alt="Logo Dblift">
</p>

**Gérez vos changements de base de données en toute confiance**

DBLift vous aide à suivre et appliquer les changements de base de données de manière systématique. Pensez-y comme un contrôle de version pour votre schéma de base de données - chaque changement est suivi, peut être annulé et fonctionne de manière cohérente dans différents environnements.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Java](https://img.shields.io/badge/Java-11%2B-orange)
![License](https://img.shields.io/badge/License-Proprietary-red)
[![Tests](https://github.com/cmodiano/dblift/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/cmodiano/dblift/actions/workflows/unit-tests.yml)
[![Code Quality](https://github.com/cmodiano/dblift/actions/workflows/code-quality.yml/badge.svg)](https://github.com/cmodiano/dblift/actions/workflows/code-quality.yml/badge.svg)
[![Coverage](https://codecov.io/gh/cmodiano/dblift/branch/main/graph/badge.svg)](https://codecov.io/gh/cmodiano/dblift/branch/main/graph/badge.svg) (Tests unitaires + intégration combinés)

---

## Démarrage Rapide

Mettez-vous en route en quelques minutes :

1. **[Installer DBLift](user-guide/getting-started.md#installation)** - Téléchargez et configurez
2. **[Créer Votre Première Migration](user-guide/getting-started.md#votre-premiere-migration)** - Apprenez les bases
3. **[Appliquer les Migrations](user-guide/commands.md#appliquer-les-changements-a-votre-base-de-donnees)** - Déployez vos changements

## Sections de Documentation

### 👤 Guide Utilisateur

Tout ce dont vous avez besoin pour utiliser DBLift efficacement :

- **[Démarrage](user-guide/getting-started.md)** - Installation et votre première migration
- **[Configuration](user-guide/configuration.md)** - Configuration de la base de données et options
- **[Commandes](user-guide/commands.md)** - Toutes les commandes disponibles et leur utilisation
- **[Meilleures Pratiques](user-guide/best-practices.md)** - Conseils pour des migrations efficaces
- **[Dépannage](user-guide/troubleshooting.md)** - Solutions aux problèmes courants

### 🔌 Référence API

Documentation API complète générée depuis le code :

- **[Client API](api-reference/api.md)** - `DBLiftClient` et opérations de haut niveau
- **[Commandes CLI](api-reference/cli.md)** - Référence de l'interface en ligne de commande
- **[Modules Core](api-reference/core.md)** - Moteur de migration, analyse SQL, et plus
- **[Fournisseurs de Base de Données](api-reference/db.md)** - Implémentations spécifiques aux bases de données

### 🏗️ Architecture

Plongée technique pour les développeurs :

- **[Vue d'ensemble](architecture/overview.md)** - Architecture système et principes de conception
- **[Moteur de Migration](architecture/migration-engine.md)** - Comment les migrations sont exécutées
- **[Fournisseurs de Base de Données](architecture/database-providers.md)** - Architecture du système de fournisseurs
- **[Analyse SQL](architecture/sql-parsing.md)** - Analyse et parsing SQL
- **[Configuration](architecture/configuration.md)** - Détails du système de configuration

### 💻 Contribuer

Contribuer à DBLift :

> **Note:** La documentation de contribution n'est actuellement disponible qu'en anglais. Veuillez consulter [CONTRIBUTING.md](../../CONTRIBUTING.md).

### 📖 Exemples

Exemples et tutoriels du monde réel :

> **Note:** Les exemples ne sont actuellement disponibles qu'en anglais. Veuillez consulter la [version anglaise](../examples/basic-migrations.md).

## Bases de Données Supportées

DBLift prend en charge les bases de données suivantes :

- **PostgreSQL** - Support natif SQLAlchemy
- **MySQL** - Support natif SQLAlchemy
- **SQL Server** - Support natif SQLAlchemy
- **Oracle** - Support natif SQLAlchemy
- **DB2** - Support natif SQLAlchemy
- **SQLite** - Support Python natif
- **Azure Cosmos DB** - Intégration Azure SDK

## Fonctionnalités Clés

- ✅ **Contrôle de Version pour Bases de Données** - Suivez chaque changement de schéma
- ✅ **Support de Rollback** - Annulez les migrations si nécessaire
- ✅ **Support Multi-Bases de Données** - Fonctionne avec 7+ types de bases de données
- ✅ **Support Baseline** - Travaillez avec des bases de données existantes
- ✅ **Comparaison de Schémas** - Comparez les états de base de données
- ✅ **Validation SQL** - Validez le SQL avant de l'appliquer
- ✅ **Migrations Étiquetées** - Organisez les migrations par fonctionnalité
- ✅ **Mode Dry-Run** - Prévisualisez les changements avant de les appliquer

## Besoin d'Aide ?

- 📖 Consultez le [Guide Utilisateur](user-guide/getting-started.md) pour les tâches courantes
- 🔍 Recherchez dans la documentation à l'aide de la barre de recherche ci-dessus
- 🐛 Trouvé un bug ? [Ouvrez une issue](https://github.com/cmodiano/dblift/issues)
- 💬 Des questions ? Consultez le guide de [Dépannage](user-guide/troubleshooting.md)

---

**Prêt à commencer ?** Passez au [Guide de Démarrage](user-guide/getting-started.md) !
