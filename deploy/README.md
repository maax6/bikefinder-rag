# Ancien déploiement Hugging Face

Ce dossier conserve les fichiers du déploiement historique et du showcase
statique. **Il ne décrit pas le parcours local actuel avec Jev** et n'est pas
activé par cette réorganisation.

Le parcours retenu est documenté dans l'[architecture actuelle](../docs/reference/architecture.md)
et le [guide local](../docs/guides/local-setup.md). Jev est le seul service
d'inférence distant autorisé ; le Dockerfile historique fixe encore
`AGENT_BACKEND=anthropic` et les anciennes pages proposent une clé visiteur.
Publier ce dossier tel quel ne respecte donc pas la configuration retenue.

| Fichier | Rôle historique |
|---|---|
| `Dockerfile` | Image Hugging Face avec PostgreSQL, BGE-M3 et Gradio |
| `entrypoint.sh` | Décompresser le PGDATA livré, démarrer PostgreSQL puis Gradio |
| `push_space.sh` | Assembler les chemins attendus puis créer/téléverser le Space distant |
| `space-README.md` | Métadonnées et présentation du Space Docker |
| `static-space-README.md`, `static-space/index.html` | Métadonnées et vitrine statique historique |
| `pgdata.tar.gz` | Archive locale de base requise par le déploiement Docker, ignorée dans GitHub |

Les chemins sont conservés : `push_space.sh` et le Dockerfile en dépendent.
`pgdata.tar.gz` et les données locales ne sont ni déplacés ni supprimés. Un
nouveau déploiement serait un travail distinct, avec configuration et données
explicites ; ces scripts ne sont pas des commandes de lancement local.
