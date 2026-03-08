import { Routes, Route, useParams, Navigate } from 'react-router-dom';
import './App.css';
import Sanctum from './main/Sanctum';
import { supportedLanguages } from './data/bibleBooks';

function LangRoute() {
  const { lang } = useParams();
  if (!supportedLanguages[lang]) {
    return <Navigate to="/" replace />;
  }
  return <Sanctum lang={lang} />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Sanctum lang="en" />} />
      <Route path="/:lang" element={<LangRoute />} />
    </Routes>
  );
}