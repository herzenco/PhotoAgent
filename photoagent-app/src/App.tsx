import { useAppContext } from './context/AppContext';
import AppShell from './components/layout/AppShell';
import WelcomeScreen from './screens/WelcomeScreen';
import DashboardScreen from './screens/DashboardScreen';
import PhotoGridScreen from './screens/PhotoGridScreen';
import PlannerScreen from './screens/PlannerScreen';
import ExecutionScreen from './screens/ExecutionScreen';
import SettingsScreen from './screens/SettingsScreen';

function App() {
  const { state } = useAppContext();

  if (!state.folderPath) return <WelcomeScreen />;

  return (
    <AppShell>
      {state.currentScreen === 'dashboard' && <DashboardScreen />}
      {state.currentScreen === 'grid' && <PhotoGridScreen />}
      {state.currentScreen === 'planner' && <PlannerScreen />}
      {state.currentScreen === 'history' && <ExecutionScreen />}
      {state.currentScreen === 'settings' && <SettingsScreen />}
    </AppShell>
  );
}

export default App;
