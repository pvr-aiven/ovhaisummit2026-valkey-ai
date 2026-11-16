# Les trois démos sur OVHcloud, en réseau privé

Ce dossier déploie les trois démos sur OVHcloud avec une base **Managed Valkey 9.1 sans adresse publique** : seule la VM des démos, sur le même sous-réseau privé, peut la joindre. Le public ouvre les interfaces à travers un load balancer filtré par IP.

## Ce qui est déployé

```
 Navigateurs (IP de demo_cidrs)
        │ TCP 8000-8002                        ┌──────────────► AI Endpoints (API publique)
        ▼                                      │
 ┌── sous-réseau privé 10.42.0.0/24 (vRack) ───┼─────────────────────────────┐
 │  Load balancer S ──► VM b3-16 (10.42.0.10) ─┴─► Gateway S (sortie Internet) │
 │  IP flottante         3 démos Docker                                        │
 │                          │ rediss:// (TLS)                                  │
 │                          ▼                                                  │
 │                 Managed Valkey 9.1 (Discovery b3-4)                         │
 │                 n'accepte que 10.42.0.0/24                                  │
 └─────────────────────────────────────────────────────────────────────────────┘
```

| Ressource | Rôle |
|---|---|
| Réseau privé + sous-réseau `10.42.0.0/24` | vRack, DHCP, IP de passerelle (exigée par le service de base de données) |
| Gateway S | sortie Internet de la VM : AI Endpoints, PyPI, Docker Hub, Hugging Face |
| Managed Valkey 9.1, Discovery b3-4 | réseau privé uniquement, `ip_restrictions` = le sous-réseau |
| VM b3-16, Ubuntu 24.04 | **sans IP publique**, IP fixe `10.42.0.10` ; cloud-init installe Docker et clone ce dépôt |
| Load balancer S + IP flottante | seule entrée publique : port 22 limité à `admin_cidr`, ports 8000-8002 limités à `demo_cidrs` |

Les ports 8000-8002 sont en **TCP de bout en bout** : le load balancer ne met pas en tampon les réponses en streaming (SSE) des démos 2 et 3, et le délai d'inactivité est de 300 s, assez pour une réponse longue de `gpt-oss-120b`.

## Prérequis

- Un projet Public Cloud **rattaché à un vRack**.
- Des identifiants de l'API OVHcloud dans `~/.ovh.conf` (ou les variables `OVH_*`), avec les droits `GET`, `POST`, `PUT` et `DELETE` sur `/cloud/project/<id>/*`.
- Terraform ≥ 1.9, Python 3, `ssh` et `scp`.
- Une clé API AI Endpoints pour les démos 2 et 3 : Control Panel > Public Cloud > AI Endpoints > API keys.

## Mode opératoire

### 1. Trouver l'image et le gabarit de la VM

```bash
cd infra/ovhcloud
P=<id du projet>
./ovhapi.py GET "/cloud/project/$P/image?osType=linux&region=EU-WEST-PAR" | tail -n +2 |
  python3 -c 'import json, sys; print(*[i["id"] for i in json.load(sys.stdin) if i["name"] == "Ubuntu 24.04"])'
./ovhapi.py GET "/cloud/project/$P/flavor?region=EU-WEST-PAR" | tail -n +2 |
  python3 -c 'import json, sys; print(*[f["id"] for f in json.load(sys.stdin) if f["name"] == "b3-16" and f["osType"] == "linux"])'
```

Chaque commande affiche un seul identifiant.

### 2. Renseigner les variables

```bash
cp terraform.tfvars.example terraform.tfvars    # jamais versionné
```

Compléter `project_id`, `image_id`, `flavor_id`, `ssh_public_key`, `admin_cidr` (votre IP publique, en `/32`) et `demo_cidrs` (les IP autorisées à ouvrir les démos).

### 3. Créer l'infrastructure

```bash
terraform init
terraform apply
```

Compter une dizaine de minutes : le service Valkey est le plus long à créer.

### 4. Générer les fichiers d'environnement

```bash
./render-env.sh
```

Le script réinitialise le mot de passe de l'utilisateur `default` par l'API et écrit `env-out/<démo>/ovhcloud.env` (mode `0600`). Le mot de passe n'est jamais affiché.

### 5. Déposer la clé AI Endpoints

```bash
# coller la clé dans env-out/ai-endpoints.key, puis :
chmod 600 env-out/ai-endpoints.key
```

### 6. Déployer les démos

```bash
./deploy.sh                          # les trois démos
./deploy.sh demo-2-rag               # ou seulement certaines
SSH_KEY=~/.ssh/ma_cle ./deploy.sh    # si la clé SSH n'est pas celle par défaut
```

Le script attend la fin de cloud-init, copie les fichiers d'environnement et les surcharges Compose (`compose-override/`), écrit `env/secrets.env` des démos 2 et 3 à partir de la clé (transmise par l'entrée standard, jamais affichée), puis lance `make prepare TARGET=ovhcloud` et `make up TARGET=ovhcloud` pour chaque démo. La démo 1 télécharge son jeu de données et ses modèles : 10 à 15 min la première fois.

Les interfaces : `http://<lb_public_ip>:8000` (démo 1), `:8001` (démo 2) et `:8002` (démo 3), avec `terraform output -raw lb_public_ip`.

Pour vérifier que la base n'a pas d'adresse publique : son nom d'hôte (`terraform output -raw valkey_host`) se résout en une adresse `10.42.0.x`, et une connexion depuis votre portable échoue.

## Le jour J

Ajouter l'IP publique du réseau de la salle à `demo_cidrs`, puis :

```bash
terraform apply
```

Le load balancer est recréé (environ 3 minutes d'interruption), mais **son IP publique ne change pas** : l'IP flottante est une ressource à part.

## À savoir

- **Utilisateur `default`.** Les démos s'y connectent, car les commandes `FT.*` ne peuvent pas être accordées à un utilisateur créé par l'API.
- **Chaque `./render-env.sh` réinitialise le mot de passe.** Relancer ensuite `./deploy.sh` pour que les démos reprennent le nouveau.
- **HTTP simple.** Le filtrage par IP du load balancer est la seule protection : la démo 1 n'a pas d'authentification, et `/api/stock` écrit dans Valkey.
- **Load balancer « classique ».** `ovh_cloud_project_loadbalancer` est marqué obsolète par le provider : son remplaçant, `ovh_cloud_loadbalancer`, passe par l'API v2, qui exige une autorisation IAM (`loadbalancer/usePublicIP`) qu'une clé d'application `~/.ovh.conf` ne peut pas porter.
- **Facturation à l'heure** (gateway, VM, Valkey, load balancer, IP flottante) jusqu'à la destruction :

```bash
terraform destroy
```
