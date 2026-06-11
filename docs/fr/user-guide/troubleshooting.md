# Dépannage

Problèmes courants et leurs solutions.

## Erreur "Migration déjà appliquée"

**Problème** : Vous voyez une erreur indiquant qu'une migration a déjà été appliquée.

**Solution** : Vérifiez quelles migrations sont appliquées :
```bash
dblift info
```

Si vous voyez la migration listée comme appliquée, elle a déjà été exécutée. Si vous devez faire des changements, créez une nouvelle migration à la place.

!!! tip "Prévention"
    Vérifiez toujours `dblift info` avant de créer de nouvelles migrations pour éviter les conflits de version.

## Impossible de Se Connecter à la Base de Données

**Problème** : DBLift ne peut pas se connecter à votre base de données.

**Solution** : 
1. Vérifiez que votre fichier `dblift.yaml` contient les bons détails de connexion
2. Vérifiez que votre base de données est en cours d'exécution
3. Testez la connexion avec votre client de base de données d'abord
4. Assurez-vous que votre nom d'utilisateur et mot de passe sont corrects
5. Vérifiez les paramètres de pare-feu/réseau

**Commandes de Diagnostic :**
```bash
dblift db check-connection
dblift db diagnose-connection
dblift db validate-config
```

## Migrations Appliquées par Erreur

**Problème** : Vous avez appliqué des migrations à la mauvaise base de données ou devez annuler des changements.

**Solution** : Utilisez la commande undo :
```bash
# Revenir à une version spécifique
dblift undo --target-version=1.0.0
```

!!! note "Migrations d'Annulation Requises"
    Vous avez besoin de migrations d'annulation (`U*.sql` fichiers) pour que cela fonctionne. Voir [Annuler les Changements](commands.md#annuler-les-changements) pour les détails.

## Problèmes d'Encodage ou de Caractères Spéciaux

**Problème** : Les caractères spéciaux (é, ñ, ö, etc.) dans vos fichiers SQL ne fonctionnent pas.

**Solution** : Ajoutez l'encodage à votre `dblift.yaml` :
```yaml
migrations:
  script_encoding: "utf-8"
```

Par défaut, DBLift lit les fichiers de migration strictement avec `script_encoding`. Pour des fichiers hérités dont l'encodage est mélangé ou inconnu, activez la détection :

```yaml
migrations:
  script_encoding: "utf-8"
  detect_encoding: true
```

Si la détection ou le décodage échoue, DBLift s'arrête avec une erreur d'encodage afin de ne pas corrompre silencieusement les caractères accentués.

## Migration Hors Ordre

**Problème** : Quelqu'un a créé une migration avec un numéro de version plus ancien que ce qui est déjà appliqué.

**Solution** : 
1. Renommez le fichier de migration avec un numéro de version plus récent
2. Ou utilisez `--mark-as-executed` si vous devez le sauter :
```bash
dblift migrate --mark-as-executed --versions=1.0.5
```

!!! warning "Utiliser avec Précautions"
    Utilisez `--mark-as-executed` uniquement si vous êtes certain que les changements de la migration sont déjà dans la base de données.

## Commandes de Diagnostic

Utilisez ces commandes pour recueillir des informations :

```bash
# Vérifier la configuration
dblift db validate-config

# Tester la connexion
dblift db check-connection

# Diagnostiquer les problèmes de connexion
dblift db diagnose-connection

# Lister les pilotes disponibles
dblift db list-drivers

# Vérifier le statut des migrations
dblift info

# Valider les migrations
dblift validate
```

## Prochaines Étapes

- Consultez la **[Référence des Commandes](commands.md)** pour toutes les options disponibles
- Vérifiez les **[Meilleures Pratiques](best-practices.md)** pour éviter les problèmes courants
- Voir le **[Guide de Configuration](configuration.md)** pour les options de configuration
