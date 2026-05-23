---
name: mobile-app-builder
description: >
  Build complete, production-ready Android & iOS mobile apps from A to Z using React Native + Expo.
  Use this skill whenever the user wants to create a mobile app, phone app, Android app, iOS app,
  cross-platform app, or anything involving React Native / Expo. Also trigger when the user says
  "build me an app", "make an app for...", "I need a mobile app", "create an app", "app bouwen",
  or mentions any app concept (social, e-commerce, SaaS, utility, game, fitness, food, chat, etc.).
  Covers: full project scaffolding, navigation, screens, custom API backend, authentication,
  database, .env configuration, theming, build pipeline, and deployment to App Store & Play Store.
  Even if the user only mentions a vague idea, trigger this skill and interview them to refine it.
argument-hint: "<app idea or description>"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent
---

# Mobile App Builder

Build any mobile app from idea to deployment. This skill generates a complete React Native + Expo
project with a custom API backend, ready to build for both Android and iOS.

## Philosophy

This skill is **app-type agnostic**. Whether the user wants a social network, a webshop, a
dashboard, a game, a fitness tracker, or anything else — the same architecture adapts. The skill
interviews the user to understand their needs, then generates a tailored project.

---

## Step 0: Interview the User

Before writing any code, understand what we're building. Ask these questions (skip any already
answered in the conversation):

1. **App concept** — What does the app do? Who is it for?
2. **Core screens** — What are the 3-5 most important screens?
3. **Auth** — Do users need to log in? (email/password, social login, magic link?)
4. **Data** — What data does the app store? (users, posts, products, orders, messages, etc.)
5. **Features** — Check which apply: push notifications, payments, real-time/chat, maps,
   camera/media, offline support, analytics, admin panel
6. **Design** — Any color scheme, brand, or style preference? Dark mode?
7. **Backend** — Custom API (Node/Express, Python/FastAPI, etc.) or BaaS?

Collect answers, then confirm: "Here's what I'll build: [summary]. Ready to go?"

---

## Step 1: Scaffold the Project

After confirmation, generate the full project.

### Core Setup

```bash
# Initialize Expo project
npx create-expo-app@latest [app-name] --template blank-typescript
cd [app-name]

# Install core dependencies
npx expo install expo-router expo-linking expo-constants expo-status-bar
npx expo install react-native-safe-area-context react-native-screens
npx expo install react-native-gesture-handler react-native-reanimated
npx expo install @react-native-async-storage/async-storage
npx expo install expo-secure-store expo-splash-screen expo-font
```

### Conditional Installs (based on user features)

Only install what the user actually needs:

| Feature            | Packages                                                      |
|--------------------|---------------------------------------------------------------|
| Push notifications | `expo-notifications expo-device`                              |
| Camera / media     | `expo-image-picker expo-camera expo-media-library`            |
| Maps               | `react-native-maps expo-location`                             |
| Payments           | `@stripe/stripe-react-native` or `expo-in-app-purchases`     |
| Real-time / chat   | `socket.io-client` or `@supabase/realtime-js`                |
| Animations         | `react-native-reanimated moti`                                |
| Forms              | `react-hook-form zod @hookform/resolvers`                     |
| State management   | `zustand` (lightweight) or `@tanstack/react-query` (server)   |
| Icons              | `@expo/vector-icons` (included) or `lucide-react-native`     |
| Offline support    | `@tanstack/react-query` with `persistQueryClient`             |

---

## Step 2: Generate the .env

Create TWO files:
- `.env` — actual secrets (added to .gitignore)
- `.env.example` — same keys with placeholder values and comments explaining where to get each key

Include sections for: API URL, auth secrets, payment keys, push notification keys, any
third-party services the user needs.

---

## Step 3: Build the Backend API

The default backend stack is **Node.js + Express + TypeScript + Prisma + PostgreSQL**.
If the user prefers Python, use **FastAPI + SQLAlchemy + PostgreSQL**.

### Backend generates:

1. **Database schema** (Prisma or SQLAlchemy models) based on the user's data needs
2. **Auth system** — JWT-based with refresh tokens, stored in `expo-secure-store` on the client
3. **REST API routes** — CRUD for every entity the user described
4. **Middleware** — auth, error handling, rate limiting, CORS, request validation (zod)
5. **Docker setup** — `Dockerfile` + `docker-compose.yml` for local dev and deployment

---

## Step 4: Build the App Screens

For each screen the user described, generate:

1. **Screen component** in `app/` directory (expo-router file-based routing)
2. **UI components** in `components/` — reusable, themed, accessible
3. **API hooks** in `hooks/` — data fetching with `@tanstack/react-query`
4. **Type definitions** in `types/` — shared between frontend and backend

### Screen generation pattern:

```typescript
// app/(tabs)/home.tsx — Example screen
import { View, Text, FlatList } from 'react-native';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { ThemedView } from '@/components/ThemedView';

export default function HomeScreen() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['items'],
    queryFn: () => api.get('/items'),
  });

  return (
    <ThemedView>
      {/* Screen content */}
    </ThemedView>
  );
}
```

### Theming System

Always generate a complete theme system:

```
lib/
├── theme.ts           # Colors, spacing, typography, shadows
├── ThemeProvider.tsx  # Context provider with dark mode support
└── useTheme.ts        # Hook for accessing theme in components
```

---

## Step 5: Configure Build & Deploy

### Build pipeline:

```bash
# Install EAS CLI
npm install -g eas-cli

# Configure EAS
eas build:configure

# Build for both platforms
eas build --platform all

# Submit to stores
eas submit --platform all

# OTA updates (no store review needed for JS changes)
eas update
```

### eas.json template:

```json
{
  "cli": { "version": ">= 5.0.0" },
  "build": {
    "development": {
      "developmentClient": true,
      "distribution": "internal"
    },
    "preview": {
      "distribution": "internal",
      "ios": { "simulator": true }
    },
    "production": {
      "autoIncrement": true
    }
  },
  "submit": {
    "production": {}
  }
}
```

---

## Step 6: Generate Documentation

Create a `README.md` in the project root with:

1. Project overview and screenshots placeholder
2. Prerequisites (Node.js, Expo CLI, EAS CLI)
3. Setup instructions (clone, install, configure .env)
4. Running locally (frontend + backend)
5. Building for production
6. Deployment guide
7. Project structure overview
8. API documentation summary

---

## Output Checklist

Before presenting the final result, verify:

- [ ] All files created and no import errors
- [ ] `.env.example` has every required key with comments
- [ ] Backend runs with `docker-compose up`
- [ ] Frontend runs with `npx expo start`
- [ ] Navigation works between all screens
- [ ] Auth flow complete (register → login → protected routes)
- [ ] Theme supports light and dark mode
- [ ] TypeScript has zero errors
- [ ] README is complete and accurate

---

## Adaptation Guide

This skill adapts to ANY app type:

| App Type       | Key Additions                                                    |
|----------------|------------------------------------------------------------------|
| Social         | Feed algorithm, follow system, real-time notifications, media    |
| E-commerce     | Product catalog, cart, checkout, Stripe, order management        |
| SaaS/Dashboard | Charts (recharts), data tables, role-based access, admin panel   |
| Chat/Messaging | WebSocket (socket.io), message queue, media sharing, presence    |
| Fitness        | Health APIs, charts, progress tracking, workout timer            |
| Food/Delivery  | Maps, real-time tracking, order flow, restaurant management      |
| Education      | Course structure, progress, quizzes, video player, certificates  |
| Marketplace    | Listings, search/filter, reviews, messaging, escrow payments     |

The core architecture (auth, API, navigation, theming) stays the same — only the screens,
models, and feature-specific packages change.
