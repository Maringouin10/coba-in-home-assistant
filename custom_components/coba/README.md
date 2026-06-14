# COBA / ColNET — Intégration Home Assistant

Intégration **Home Assistant** pour le portail étudiant **COBA / ColNET** (logiciel
de gestion pédagogique collégiale utilisé par les cégeps/collèges au Québec).
Elle se connecte au portail avec votre **URL**, **nom d'utilisateur** et **mot de
passe**, puis expose vos informations scolaires sous forme de capteurs.

> ⚠️ COBA/ColNET n'offre pas d'API publique. L'intégration ouvre une session web
> comme le ferait un navigateur (et l'application *COBA Campus*) et lit les pages
> *Messagerie*, *Résultats*, *Horaire* et *Suivi*.

## Capteurs créés

| Capteur | Description |
|--------|-------------|
| `sensor.coba_..._messages_recus` | **Nombre de messages reçus** (état) + liste et nombre de non‑lus en attributs |
| `sensor.coba_..._dernier_message` | **Dernier message** (expéditeur — objet) + détails en attributs |
| `sensor.coba_..._derniere_note` | **Dernière note** (résultat) + cours / évaluation / date en attributs |
| `sensor.coba_..._prochains_cours` | **Prochain cours** (état) + **les 5 prochains cours** dans l'attribut `cours` |
| `sensor.coba_..._dernier_suivi` | **Dernier suivi** (date — type — description) + détails en attributs |

Tous les capteurs sont regroupés sous un même appareil **COBA (utilisateur)**.

## Configuration

À l'ajout de l'intégration, trois champs sont demandés :

- **Adresse du portail (URL)** — p. ex. `https://moncollege.coba.ca/colnet/login.asp`
  (l'URL exacte dépend de votre établissement ; le `/colnet/` est déduit
  automatiquement si vous ne le mettez pas).
- **Nom d'utilisateur** — votre code d'usager / numéro de DA.
- **Mot de passe** — votre mot de passe ColNET.

Options (⚙️ *Configurer*) :

- **Intervalle de rafraîchissement** (minutes, défaut 15, minimum 5).
- **Journalisation de débogage** — écrit dans le journal HA le HTML récupéré de
  chaque section, utile pour ajuster l'analyse à un portail particulier.

## Installation

### Manuelle (recommandée ici)

Copiez le dossier `custom_components/coba` dans le répertoire `custom_components`
de votre installation Home Assistant, puis redémarrez. Ajoutez ensuite
l'intégration via **Paramètres → Appareils et services → Ajouter une intégration
→ COBA**.

### Via HACS

HACS ne gère **qu'une seule intégration par dépôt** (la première du dossier
`custom_components/`). Comme ce dépôt contient aussi `claude_status`, COBA doit
être placée dans son **propre dépôt** pour apparaître comme carte HACS, ou être
installée manuellement (ci‑dessus).

## Adaptation à votre portail

Chaque cégep peut présenter de légères différences de mise en page. Toute la
logique propre au portail est isolée dans `api.py` :

- la **détection du formulaire de connexion** est automatique (champ mot de passe
  + champs cachés repris tels quels) ;
- la **découverte des sections** se fait par mots‑clés sur le texte des liens du
  menu (tolérante aux accents et variations) ;
- l'**analyse des tableaux** mappe les colonnes par en‑têtes (`Objet`,
  `Expéditeur`, `Note`, `Cours`, `Date`, …) avec repli sur les cellules brutes.

Si une section ne se remplit pas correctement, activez l'option de débogage,
récupérez le HTML depuis les journaux et ajustez les mots‑clés dans
`const.py` (`SECTION_KEYWORDS`) ou les correspondances de colonnes dans `api.py`.

## Pré‑requis

- Home Assistant récent (2024.11+ recommandé).
- Accès réseau de Home Assistant vers le portail de votre établissement.
