# Exemples de Migrations NoSQL pour DBLIFT

Ce répertoire contient des exemples de migrations MongoDB en Python pour illustrer le concept de migrations non-SQL dans DBLIFT.

## 📁 Contenu

### Migrations Python pour MongoDB

1. **`V1_0_0__create_users_collection.py`**
   - Création de la collection `users`
   - Validation de schéma JSON
   - Index multiples (unique, composite, text search)
   - Insertion d'un utilisateur admin par défaut

2. **`V1_0_1__add_user_preferences.py`**
   - Ajout d'un sous-document `preferences`
   - Migration de données existantes
   - Mise à jour de la validation de schéma
   - Création d'index sur le nouveau champ

## 🚀 Utilisation

### Prérequis

```bash
# Installer PyMongo
pip install pymongo

# Avoir MongoDB en cours d'exécution (local ou Docker)
docker run -d -p 27017:27017 --name mongodb mongo:6.0
```

### Configuration DBLIFT

**`dblift.yaml`**
```yaml
database:
  type: "mongodb"
  connection_string: "mongodb://localhost:27017"
  database_name: "myapp"
  
  nosql:
    default_format: "python"
    enable_transactions: true
    rollback_strategy: "script"

migrations:
  directory: "./migrations"
  accepted_formats:
    - "sql"
    - "python"
```

### Exécution des Migrations

```bash
# Dry-run (affiche le plan sans exécuter)
dblift migrate --dry-run

# Exécution réelle
dblift migrate

# Rollback vers une version spécifique
dblift undo --target-version=1.0.0

# Informations sur les migrations
dblift info
```

## 📖 Structure d'une Migration Python

```python
"""
Documentation de la migration.
Explique ce que fait la migration et pourquoi.
"""

def upgrade():
    """
    Fonction appelée lors de l'application de la migration.
    
    Variables disponibles :
        - client : MongoClient PyMongo
        - log : Logger DBLIFT
        - config : Configuration DBLIFT
    """
    db = client.get_database()
    
    # Votre code ici
    db.collection.insert_one({...})
    
    log.info("Migration applied successfully")


def downgrade():
    """
    Fonction appelée lors du rollback.
    
    Doit annuler toutes les modifications faites par upgrade().
    """
    db = client.get_database()
    
    # Code de rollback
    db.collection.drop()
    
    log.info("Migration rolled back successfully")


# Métadonnées optionnelles
__migration_metadata__ = {
    'author': 'Team Name',
    'jira_ticket': 'PROJ-123',
    'estimated_duration_seconds': 5,
    'breaking_change': False
}
```

## ✅ Bonnes Pratiques

### 1. Toujours Implémenter `downgrade()`

Même si vous ne prévoyez pas de faire de rollback, implémentez `downgrade()` pour documenter comment annuler la migration.

**Bon ✅**
```python
def upgrade():
    db.create_collection('users')

def downgrade():
    db.users.drop()
```

**Mauvais ❌**
```python
def upgrade():
    db.create_collection('users')

# Pas de downgrade() - rollback impossible
```

### 2. Utiliser des Transactions Quand Possible

```python
def upgrade():
    db = client.get_database()
    
    # Avec transaction pour garantir l'atomicité
    with client.start_session() as session:
        with session.start_transaction():
            db.users.insert_one({...}, session=session)
            db.audit.insert_one({...}, session=session)
    
    log.info("Transaction committed")
```

### 3. Logger Abondamment

```python
def upgrade():
    db = client.get_database()
    
    log.info("Starting migration...")
    
    log.info("Creating collection...")
    db.create_collection('users')
    log.info("✓ Collection created")
    
    log.info("Creating indexes...")
    db.users.create_index('email', unique=True)
    log.info("✓ Indexes created")
    
    log.info("Migration completed successfully!")
```

### 4. Gérer les Cas d'Idempotence

Vos migrations doivent être idempotentes quand possible :

```python
def upgrade():
    db = client.get_database()
    
    # Vérifie si la collection existe déjà
    if 'users' in db.list_collection_names():
        log.warning("Collection 'users' already exists, skipping creation")
        return
    
    # Crée seulement si elle n'existe pas
    db.create_collection('users')
    log.info("✓ Created 'users' collection")
```

### 5. Valider les Données Avant Migration

```python
def upgrade():
    db = client.get_database()
    
    # Compte les documents à migrer
    count = db.old_users.count_documents({})
    log.info(f"Found {count} users to migrate")
    
    if count == 0:
        log.warning("No users to migrate")
        return
    
    # Migration...
    migrated = 0
    for user in db.old_users.find():
        db.new_users.insert_one(transform_user(user))
        migrated += 1
        
        if migrated % 1000 == 0:
            log.info(f"Migrated {migrated}/{count} users...")
    
    log.info(f"✓ Migrated all {migrated} users")
```

### 6. Documenter les Métadonnées

```python
__migration_metadata__ = {
    'author': 'DevOps Team',
    'jira_ticket': 'PROJ-123',
    'description': 'Detailed description of what this does',
    'estimated_duration_seconds': 30,
    'breaking_change': False,
    'requires_downtime': False,
    'collections_affected': ['users', 'audit_logs'],
    'indexes_created': ['idx_email_unique'],
    'dependencies': ['V1_0_0__create_base_collections.py']
}
```

## 🔒 Sécurité

### Modules Autorisés

Les migrations Python s'exécutent dans un environnement restreint avec une liste blanche de modules :

**✅ Autorisés :**
- `datetime`
- `json`
- `re`
- `math`
- `collections`
- `itertools`
- `pymongo` (pour MongoDB)

**❌ Interdits :**
- `os`
- `subprocess`
- `sys`
- `__import__`
- `eval`
- `exec`

### Timeout

Toutes les migrations ont un timeout par défaut (configurable) :
- **Default** : 300 secondes (5 minutes)
- **Configurable** dans `dblift.yaml`

## 🧪 Tests

### Test en Local

Avant de commiter une migration, testez-la localement :

```bash
# 1. Dry-run
dblift migrate --dry-run

# 2. Test sur base de test
DBLIFT_DB_DATABASE_NAME=test_db dblift migrate

# 3. Vérification
mongo test_db --eval "db.users.find().pretty()"

# 4. Rollback
dblift undo --target-version=1.0.0

# 5. Vérification du rollback
mongo test_db --eval "db.getCollectionNames()"
```

### Tests Automatisés

```python
# tests/test_migrations.py

import pytest
from pymongo import MongoClient
from testcontainers.mongodb import MongoDbContainer

def test_v1_0_0_migration():
    """Test de la migration V1.0.0."""
    with MongoDbContainer("mongo:6.0") as container:
        client = MongoClient(container.get_connection_url())
        db = client.test_db
        
        # Exécute upgrade()
        exec(open('V1_0_0__create_users_collection.py').read(), {
            'client': client,
            'log': MockLogger()
        })
        
        # Vérifie que la collection existe
        assert 'users' in db.list_collection_names()
        
        # Vérifie les index
        indexes = list(db.users.list_indexes())
        assert any(idx['name'] == 'idx_email_unique' for idx in indexes)
```

## 📚 Ressources

### Documentation
- [MongoDB Python Driver](https://pymongo.readthedocs.io/)
- [MongoDB Schema Validation](https://www.mongodb.com/docs/manual/core/schema-validation/)
- [MongoDB Indexes](https://www.mongodb.com/docs/manual/indexes/)

### Outils
- [MongoDB Compass](https://www.mongodb.com/products/compass) - GUI MongoDB
- [Studio 3T](https://studio3t.com/) - IDE MongoDB
- [testcontainers](https://testcontainers-python.readthedocs.io/) - Tests d'intégration

## ❓ FAQ

### Q : Puis-je utiliser des bibliothèques tierces ?
**R** : Oui, mais elles doivent être dans la liste blanche de sécurité. Contactez l'équipe pour ajouter une bibliothèque.

### Q : Comment gérer les migrations longues ?
**R** : 
1. Augmenter le timeout dans la configuration
2. Logger la progression régulièrement
3. Considérer le batching pour les grosses migrations de données

### Q : Que faire si une migration échoue en production ?
**R** :
1. Exécuter le rollback : `dblift undo`
2. Corriger la migration
3. Tester en dev/staging
4. Ré-exécuter en production

### Q : Peut-on exécuter plusieurs migrations en parallèle ?
**R** : Non, par défaut les migrations sont séquentielles pour garantir la cohérence. Pour du parallélisme, utilisez des tags.

---

**Note** : Ces exemples sont des concepts pour illustrer l'approche proposée. L'implémentation réelle nécessite le développement décrit dans [MONGODB_POC_IMPLEMENTATION.md](../../docs/MONGODB_POC_IMPLEMENTATION.md).
