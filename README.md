# BruteScope - Groupe 20

Projet pedagogique de securite informatique pour observer une attaque par dictionnaire contre un formulaire d'authentification web dans un environnement Docker local et controle.

## Architecture

- `target` : application Flask volontairement vulnerable, exposee sur `localhost:8081`.
- `api` : API Flask qui orchestre Hydra et diffuse les resultats en Server-Sent Events, exposee sur `localhost:5055`.
- `frontend` : dashboard web servi par nginx, expose sur `localhost:3000`.

Le test est limite par defaut aux cibles Docker du laboratoire (`target` et `172.20.0.10`).

## Demarrage

```powershell
cd D:\brute_force_tester_groupe20\project
docker compose up -d
```

Si les images doivent etre reconstruites :

```powershell
docker compose up -d --build
```

## Verification

```powershell
docker compose ps
```

Les trois conteneurs doivent etre `healthy` :

- `bf_target`
- `bf_api`
- `bf_frontend`

## Acces

- Dashboard : http://localhost:3000
- API : http://localhost:5055/api/status
- Cible vulnerable : http://localhost:8081

## Arret propre

```powershell
cd D:\brute_force_tester_groupe20\project
docker compose down
```

## Cadre ethique

Ce projet est strictement educatif. Il doit etre utilise uniquement sur l'environnement local fourni ou sur des systemes pour lesquels une autorisation explicite de test a ete obtenue.
