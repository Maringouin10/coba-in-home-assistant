# COBA / ColNET — Intégration Home Assistant

Intégration **Home Assistant** pour le portail étudiant **COBA / ColNET** (cégeps /
collèges, Québec). Connexion par **URL + nom d'utilisateur + mot de passe**, puis
exposition des informations scolaires en capteurs.

> COBA/ColNET n'a pas d'API publique : l'intégration ouvre une session web (comme
> un navigateur / l'app *COBA Campus*) et lit les pages Messagerie, Résultats,
> Horaire et Suivi.

## Capteurs

| Capteur | Description |
|--------|-------------|
| **Messages reçus** | nombre de messages (+ liste et non-lus en attributs) |
| **Dernier message** | expéditeur — objet (+ détails) |
| **Dernière note** | dernier résultat (+ cours / évaluation / date) |
| **Prochains cours** | prochain cours (état) + **les 5 prochains** dans l'attribut `cours` |
| **Dernier suivi** | date — type — description |

## Installation via HACS

1. HACS → menu ⋮ → **Dépôts personnalisés**
2. URL : `https://github.com/Maringouin10/coba-homeassistant` — catégorie **Intégration**
3. **Télécharger** la carte *COBA / ColNET*, puis redémarrer Home Assistant
4. **Paramètres → Appareils et services → Ajouter une intégration → COBA**
5. Saisir l'**URL** du portail (ex. `https://moncollege.coba.ca/colnet/login.asp`),
   le **nom d'utilisateur** (code d'usager / DA) et le **mot de passe**

## Options

⚙️ *Configurer* : intervalle de rafraîchissement (min. 5 min, défaut 15) et
**journalisation de débogage** (écrit le HTML des sections dans le journal HA pour
ajuster l'analyse à un portail particulier).

## Adaptation

Toute la logique propre au portail est dans `custom_components/coba/api.py`
(détection auto du formulaire de login, découverte des sections par mots-clés,
analyse des tableaux par en-têtes). Mots-clés ajustables dans `const.py`
(`SECTION_KEYWORDS`).

## Pré-requis

- Home Assistant 2024.11+ recommandé
- Accès réseau de Home Assistant vers le portail de l'établissement
