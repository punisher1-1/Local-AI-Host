# Local AI Custom Frontend - Project Notes

This document captures the initial setup, design decisions, and future roadmap discussions for the custom local AI frontend project.

## Project Overview

We created a custom frontend application to serve as a scalable, in-house alternative to AnythingLLM and Open WebUI. It is designed to interface with the existing backend stack (FastAPI, SQLAlchemy, PostgreSQL, and pgVector).

### Technology Stack
- **Framework:** React with Vite (for fast local development and optimized production builds)
- **Styling:** Custom Vanilla CSS (implementing modern CSS variables, Flexbox, and glassmorphism)
- **State Management:** React Hooks for UI state and chat sessions.

## Features Implemented (Proof of Concept)

- **Vite React Architecture:** A lightweight, scalable SPA structure.
- **Modern Design System (`index.css`):**
  - "Dark Mode by default" aesthetic.
  - Glassmorphism utility classes and subtle gradient overlays.
  - Custom scrollbars and modern typography (Inter font).
- **Layout Shell:** A responsive layout featuring a fixed sidebar and a central chat area.
- **Sidebar (`Sidebar.jsx`):**
  - Manages chat history navigation.
  - Includes a "New Chat" button, a "Settings" button, and a **Feedback button** (tied to a `mailto:` link for user trials).
- **Chat Interface (`ChatArea.jsx` & `MessageBubble.jsx`):**
  - Distinct styling for user messages (solid accent) vs. AI messages (glassmorphic with outlines).
  - Sticky input area (`ChatInput.jsx`) with an attachment button intended for future RAG document uploads.
- **Settings Modal (`SettingsModal.jsx`):**
  - Configurable tabs for general settings, model selection, and vector database connection strings.

*(Note: The current UI is wired with mock state. The next development phase will involve replacing this state with `fetch` or `axios` calls to the FastAPI backend.)*

## Running the Project Locally

To run the frontend locally and verify the UI:

```bash
cd ai-frontend
npm install
npm run dev
```

Navigate to the provided localhost URL (typically `http://localhost:5173`) in your browser.

---

## Future Roadmap: Admin Portal

During the trial phase, we discussed scaling the application to include an Admin Portal. When ready to build this, we will need to address the following technical requirements:

1. **Authentication & Authorization**
   - Determine how admins log in.
   - Implement Role-Based Access Control (RBAC) in the FastAPI backend (e.g., via JWTs, OAuth like Okta/Entra ID, or sessions) to securely verify admin privileges.

2. **Core Admin Features**
   - **User Management:** Create, view, or restrict user accounts.
   - **Analytics & Observability:** Monitor chat usage, token consumption, and model performance.
   - **RAG / Vector DB Management:** An interface to directly upload, view, or manage documents stored in pgVector.
   - **Global Configuration:** Manage system-wide prompts, default models, and API keys.

3. **Architecture Strategy**
   - Decide whether the admin portal should be a protected route within this existing Vite application (e.g., `/admin`) or a completely isolated, standalone web application for enhanced security.

4. **API Endpoints**
   - The FastAPI backend will need specialized, protected routes specifically designed to serve the administrative functions.
