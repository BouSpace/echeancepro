# Déploiement d'ÉchéancePro sur un VPS (Ubuntu + Nginx + Gunicorn + PostgreSQL)

Guide pour un VPS Ubuntu 22.04 ou 24.04 (Contabo ou autre) et un nom de domaine.
Remplacez **DOMAINE** par votre nom de domaine (ex. `echeances.mon-entreprise.com`) et **IP_VPS** par l'adresse du serveur.

Organisation sur le serveur :

```
/srv/echeancepro/app/          le code (+ .venv, .env, staticfiles/)
/srv/echeancepro/media/        photos et pièces jointes (à sauvegarder)
/srv/echeancepro/sauvegardes/  sauvegardes quotidiennes
```

## 0. Avant de commencer

- Chez votre registrar : créez un enregistrement DNS **A** `DOMAINE → IP_VPS` (la propagation peut prendre quelques minutes à quelques heures).
- Un compte e-mail SMTP pour les alertes (serveur, port, identifiant, mot de passe).
- Connectez-vous au serveur : `ssh root@IP_VPS`.

## 1. Sécuriser le serveur

```bash
apt update && apt upgrade -y
adduser deploy                      # un utilisateur d'administration (choisissez un mot de passe fort)
usermod -aG sudo deploy
# Copiez votre clé SSH pour cet utilisateur (depuis votre PC) :  ssh-copy-id deploy@IP_VPS
ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw enable
apt install -y fail2ban unattended-upgrades
```

Une fois la connexion par clé vérifiée avec `deploy`, désactivez la connexion SSH de `root` et par mot de passe
(`PermitRootLogin no` et `PasswordAuthentication no` dans `/etc/ssh/sshd_config`, puis `systemctl restart ssh`).
Travaillez ensuite en `deploy`, avec `sudo`.

## 2. Installer les logiciels

```bash
sudo apt install -y python3-venv python3-pip nginx postgresql postgresql-contrib certbot python3-certbot-nginx
sudo timedatectl set-timezone Africa/Ouagadougou
```

## 3. Base de données

```bash
sudo -u postgres psql <<'SQL'
CREATE USER echeancepro WITH PASSWORD 'CHOISISSEZ_UN_MOT_DE_PASSE_FORT';
CREATE DATABASE echeancepro OWNER echeancepro ENCODING 'UTF8';
SQL
```

## 4. Utilisateur applicatif et dossiers

```bash
sudo adduser --system --group --home /srv/echeancepro echeancepro
sudo usermod -aG www-data echeancepro
sudo mkdir -p /srv/echeancepro/app /srv/echeancepro/media /srv/echeancepro/sauvegardes
sudo chown -R echeancepro:www-data /srv/echeancepro
sudo chmod 750 /srv/echeancepro /srv/echeancepro/media
```

## 5. Envoyer le code

Depuis votre PC (PowerShell), dans le dossier du projet. On exclut les fichiers locaux (environnement virtuel, base de test, `.env`) :

```powershell
cd d:\Mes_Dev\Web\echeancepro\echeancepro
tar --exclude=.venv --exclude=db.sqlite3 --exclude=media --exclude=staticfiles --exclude=__pycache__ --exclude=.env -czf echeancepro.tar.gz .
scp echeancepro.tar.gz deploy@IP_VPS:/tmp/
```

Sur le serveur :

```bash
sudo -u echeancepro tar -xzf /tmp/echeancepro.tar.gz -C /srv/echeancepro/app && rm /tmp/echeancepro.tar.gz
```

(Avec un dépôt git privé, vous pourrez plus tard remplacer cette étape par `git pull`.)

## 6. Environnement Python et configuration

```bash
cd /srv/echeancepro/app
sudo -u echeancepro python3 -m venv .venv
sudo -u echeancepro .venv/bin/pip install -r requirements.txt

sudo -u echeancepro cp deploy/env.production.example .env
sudo chmod 600 .env
sudo -u echeancepro nano .env       # DOMAINE, clé secrète, mot de passe PostgreSQL, SMTP…
```

Les réglages e-mail du `.env` servent de réglages par défaut : une fois connecté en superutilisateur, vous pouvez les remplacer dans l'application (menu **Administration > Alertes e-mail**), avec un bouton de test d'envoi.
Le mot de passe SMTP saisi dans l'application est chiffré avec la `SECRET_KEY` : si vous changez cette clé, il faudra le ressaisir.

Générez la clé secrète avec : `python3 -c "import secrets; print(secrets.token_urlsafe(60))"`.
L'application refuse de démarrer en production avec la clé d'exemple.

## 7. Initialiser l'application

```bash
cd /srv/echeancepro/app
sudo -u echeancepro .venv/bin/python manage.py migrate
sudo -u echeancepro .venv/bin/python manage.py collectstatic --noinput
sudo -u echeancepro .venv/bin/python manage.py init_roles
sudo -u echeancepro .venv/bin/python manage.py createsuperuser
sudo -u echeancepro .venv/bin/python manage.py check --deploy
```

## 8. Gunicorn (service)

```bash
sudo cp deploy/gunicorn.service /etc/systemd/system/echeancepro.service
sudo systemctl daemon-reload
sudo systemctl enable --now echeancepro
sudo systemctl status echeancepro      # doit afficher « active (running) »
```

## 9. Nginx

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/echeancepro
sudo sed -i 's/DOMAINE/votre-domaine.com/g' /etc/nginx/sites-available/echeancepro
sudo ln -s /etc/nginx/sites-available/echeancepro /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

## 10. HTTPS (Let's Encrypt)

Le DNS doit déjà pointer vers le serveur :

```bash
sudo certbot --nginx -d votre-domaine.com
```

Choisissez la redirection HTTP → HTTPS. Le renouvellement est automatique (`sudo certbot renew --dry-run` pour vérifier).
Ouvrez ensuite https://votre-domaine.com et connectez-vous.
Quand tout fonctionne, passez `SECURE_HSTS_SECONDS` à `3600` dans `.env`, puis plus tard à `31536000`, et redémarrez : `sudo systemctl restart echeancepro`.

## 11. Alertes e-mail quotidiennes

```bash
sudo cp deploy/alertes.service deploy/alertes.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now alertes.timer
systemctl list-timers alertes.timer      # prochaine exécution
sudo -u echeancepro /srv/echeancepro/app/.venv/bin/python /srv/echeancepro/app/manage.py envoyer_alertes   # test manuel
```

## 12. Sauvegardes

```bash
sudo chmod +x /srv/echeancepro/app/deploy/sauvegarde.sh
sudo -u echeancepro /srv/echeancepro/app/deploy/sauvegarde.sh      # test
sudo -u echeancepro crontab -e
# ajouter la ligne (tous les jours à 2 h) :
# 0 2 * * * /srv/echeancepro/app/deploy/sauvegarde.sh >> /srv/echeancepro/sauvegardes/journal.log 2>&1
```

Les sauvegardes restent **sur le même serveur** : copiez-les régulièrement ailleurs (autre serveur, stockage objet, votre PC),
sinon la perte du VPS fait perdre aussi les sauvegardes. Exemple depuis votre PC : `scp -r deploy@IP_VPS:/srv/echeancepro/sauvegardes .`
(donnez alors à `deploy` le droit de lecture, ou utilisez `sudo`).

Restauration de la base : `gunzip -c base-AAAAMMJJ-HHMM.sql.gz | sudo -u echeancepro psql echeancepro`.

## 13. Mettre à jour l'application

Envoyez le nouveau code (étape 5), puis :

```bash
cd /srv/echeancepro/app
sudo -u echeancepro .venv/bin/pip install -r requirements.txt
sudo -u echeancepro .venv/bin/python manage.py migrate
sudo -u echeancepro .venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart echeancepro
```

## Dépannage

| Symptôme | Où regarder |
| --- | --- |
| Page « 502 Bad Gateway » | `sudo systemctl status echeancepro` et `sudo journalctl -u echeancepro -n 50` |
| « Bad Request (400) » | `ALLOWED_HOSTS` et `CSRF_TRUSTED_ORIGINS` dans `.env` (domaine exact, avec `https://` pour le second) |
| Pas de style (CSS) | `collectstatic` oublié, puis `sudo systemctl restart echeancepro` |
| Photos ou pièces jointes introuvables | droits de `/srv/echeancepro/media` (groupe `www-data`, mode 750) et `MEDIA_ROOT` dans `.env` |
| Pas d'e-mail | `sudo journalctl -u alertes -n 50` et les réglages `EMAIL_*` |
| Erreur 413 à l'import | augmenter `client_max_body_size` dans la configuration Nginx |
