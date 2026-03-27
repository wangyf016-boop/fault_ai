import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import MainLayout from './components/layout/MainLayout';
import ChatPage from './pages/ChatPage';
import GraphSearchPage from './pages/GraphSearchPage';
import DatasetPage from './pages/DatasetPage';
import OcrPage from './pages/OcrPage';
import SettingsPage from './pages/SettingsPage';
import LoginPage from './pages/LoginPage';

function App() {
  // Mock authentication status
  const isAuthenticated = true;

  return (
    <Router>
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        <Route path="/" element={isAuthenticated ? <MainLayout /> : <Navigate to="/login" />}>
          <Route index element={<Navigate to="/chat" replace />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="chat/:sessionId" element={<ChatPage />} />
          <Route path="graph-search" element={<GraphSearchPage />} />
          <Route path="datasets" element={<DatasetPage />} />
          <Route path="ocr" element={<OcrPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </Router>
  );
}

export default App;
