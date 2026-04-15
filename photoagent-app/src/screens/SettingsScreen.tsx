import { useState, useEffect } from 'react';
import { Eye, EyeOff, ShieldCheck, Loader2, CheckCircle2 } from 'lucide-react';
import { usePhotoAgent } from '../hooks/usePhotoAgent';
import type { AppConfig } from '../types/cli';

export default function SettingsScreen() {
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [device, setDevice] = useState('cpu');
  const [saveSuccess, setSaveSuccess] = useState(false);

  const { execute: loadConfig, loading: configLoading, error: configError } = usePhotoAgent<AppConfig>();
  const { execute: saveApiKey, loading: saveLoading, error: saveError } = usePhotoAgent<unknown>();

  useEffect(() => {
    loadConfig(['config', '--show', '--json']).then((data) => {
      if (data) {
        setDevice(data.preferred_device || 'cpu');
        if (data.api_key_configured) {
          setApiKey('sk-...configured');
        }
      }
    });
  }, []);

  const handleSaveApiKey = async () => {
    if (!apiKey.trim()) return;
    setSaveSuccess(false);
    const result = await saveApiKey(['config', '--set-api-key', apiKey]);
    if (result !== null) {
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    }
  };

  const displayError = configError || saveError;

  return (
    <div className="p-8 max-w-2xl">
      <h1 className="text-xl font-semibold text-[#FAFAFA] mb-6">Settings</h1>

      {/* Error message */}
      {displayError && (
        <div className="mb-6 px-4 py-3 bg-[#7F1D1D]/30 border border-[#DC2626]/40 rounded-xl text-sm text-[#FCA5A5]">
          {displayError}
        </div>
      )}

      {configLoading ? (
        <div className="flex items-center justify-center py-16">
          <div className="text-center">
            <Loader2 size={32} className="text-[#6366F1] animate-spin mx-auto mb-3" />
            <p className="text-sm text-[#71717A]">Loading settings...</p>
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          {/* API Configuration */}
          <section className="bg-[#18181B] border border-[#27272A] rounded-xl p-6">
            <h2 className="text-[17px] font-semibold text-[#FAFAFA] mb-4">API Configuration</h2>
            <div className="space-y-3">
              <label className="block text-sm text-[#A1A1AA]">API Key</label>
              <div className="relative">
                <input
                  type={showKey ? 'text' : 'password'}
                  value={apiKey}
                  onChange={(e) => { setApiKey(e.target.value); setSaveSuccess(false); }}
                  placeholder="sk-..."
                  className="w-full h-10 bg-[#27272A] border border-[#3F3F46] rounded-lg px-3 pr-10 text-sm text-[#FAFAFA] placeholder:text-[#71717A] focus:outline-none focus:border-[#6366F1] transition-colors duration-150"
                />
                <button
                  onClick={() => setShowKey(!showKey)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#71717A] hover:text-[#A1A1AA] transition-colors duration-150"
                >
                  {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={handleSaveApiKey}
                  disabled={saveLoading || !apiKey.trim()}
                  className="px-4 py-2 text-sm text-[#A1A1AA] border border-[#3F3F46] hover:border-[#6366F1] hover:text-[#FAFAFA] rounded-lg transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  {saveLoading && <Loader2 size={14} className="animate-spin" />}
                  {saveLoading ? 'Saving...' : 'Save API Key'}
                </button>
                {saveSuccess && (
                  <span className="flex items-center gap-1.5 text-xs text-[#34D399]">
                    <CheckCircle2 size={14} />
                    Saved
                  </span>
                )}
              </div>
            </div>
          </section>

          {/* Analysis */}
          <section className="bg-[#18181B] border border-[#27272A] rounded-xl p-6">
            <h2 className="text-[17px] font-semibold text-[#FAFAFA] mb-4">Analysis</h2>
            <div className="space-y-3">
              <label className="block text-sm text-[#A1A1AA]">Preferred Device</label>
              <select
                value={device}
                onChange={(e) => setDevice(e.target.value)}
                className="w-full h-10 bg-[#27272A] border border-[#3F3F46] rounded-lg px-3 text-sm text-[#FAFAFA] focus:outline-none focus:border-[#6366F1] transition-colors duration-150 appearance-none"
              >
                <option value="cpu">CPU</option>
                <option value="gpu">GPU (CUDA)</option>
                <option value="mps">MPS (Apple Silicon)</option>
              </select>
            </div>
          </section>

          {/* Privacy */}
          <section className="bg-[#18181B] border border-[#27272A] rounded-xl p-6">
            <h2 className="text-[17px] font-semibold text-[#FAFAFA] mb-4 flex items-center gap-2">
              <ShieldCheck size={18} className="text-[#34D399]" />
              Privacy
            </h2>
            <div className="space-y-3 text-sm text-[#A1A1AA] leading-relaxed">
              <p>
                PhotoAgent processes all images locally on your device. Only text metadata
                (tags, captions, and file paths) is sent to the AI for organization planning.
              </p>
              <p>
                Your actual image files never leave your computer. All analysis models run
                on-device using your selected compute device.
              </p>
            </div>
          </section>

          {/* About */}
          <section className="bg-[#18181B] border border-[#27272A] rounded-xl p-6">
            <h2 className="text-[17px] font-semibold text-[#FAFAFA] mb-4">About</h2>
            <div className="space-y-2">
              {[
                { label: 'Version', value: '0.1.0' },
                { label: 'Runtime', value: 'Tauri 2.0' },
                { label: 'Engine', value: 'PhotoAgent CLI' },
              ].map((item) => (
                <div key={item.label} className="flex justify-between text-sm">
                  <span className="text-[#A1A1AA]">{item.label}</span>
                  <span className="text-[#FAFAFA] font-mono text-xs">{item.value}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
