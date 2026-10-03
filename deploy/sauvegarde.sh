#!/bin/bash
# Sauvegarde quotidienne d'ÉchéancePro : base PostgreSQL + fichiers téléversés.
# Installation : voir DEPLOIEMENT.md (étape « Sauvegardes »). À lancer en tant qu'utilisateur echeancepro.
set -euo pipefail

DEST=/srv/echeancepro/sauvegardes
MEDIA=/srv/echeancepro/media
JOURS=14
DATE=$(date +%Y%m%d-%H%M)

mkdir -p "$DEST"
umask 077

pg_dump --no-owner echeancepro | gzip > "$DEST/base-$DATE.sql.gz"
tar -czf "$DEST/media-$DATE.tar.gz" -C "$(dirname "$MEDIA")" "$(basename "$MEDIA")"

# Supprime les sauvegardes de plus de $JOURS jours
find "$DEST" -type f -mtime +"$JOURS" -delete
echo "Sauvegarde $DATE terminée."
