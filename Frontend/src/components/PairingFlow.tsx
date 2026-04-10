import { useEffect, useState } from 'react'
import { pairBridge, getBridgeStatus, getEntertainmentConfigs, deleteBridge } from '../api/hue'
import type { BridgeStatus, EntertainmentConfig } from '../api/hue'
import { Button } from './ui/button'

type Step =
  | 'checking'
  | 'unpaired'
  | 'pairing'
  | 'paired'
  | 'error'

export default function PairingFlow() {
  const [step, setStep] = useState<Step>('checking')
  const [bridgeIp, setBridgeIp] = useState('')
  const [bridgeInfo, setBridgeInfo] = useState<BridgeStatus | null>(null)
  const [configs, setConfigs] = useState<EntertainmentConfig[]>([])
  const [errorMessage, setErrorMessage] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    checkStatus()
  }, [])

  async function checkStatus() {
    setStep('checking')
    try {
      const status = await getBridgeStatus()
      if (status.paired) {
        setBridgeInfo(status)
        setStep('paired')
        loadConfigs()
      } else {
        setStep('unpaired')
      }
    } catch {
      setStep('unpaired')
    }
  }

  async function loadConfigs() {
    try {
      const cfgs = await getEntertainmentConfigs()
      setConfigs(cfgs)
    } catch {
      // Non-critical; display empty list
    }
  }

  async function handleDelete() {
    try {
      await deleteBridge()
      setBridgeInfo(null)
      setConfigs([])
      setConfirmDelete(false)
      setStep('unpaired')
    } catch {
      setErrorMessage('Failed to delete bridge.')
      setStep('error')
    }
  }

  async function handlePair() {
    setStep('pairing')
    try {
      const result = await pairBridge(bridgeIp)
      setBridgeInfo({
        paired: true,
        bridge_ip: result.bridge_ip,
        bridge_name: result.bridge_name,
      })
      setStep('paired')
      loadConfigs()
    } catch (err: unknown) {
      const status = (err as { status?: number }).status
      if (status === 403) {
        setErrorMessage('Press the link button on your Hue Bridge, then try again.')
      } else if (status === 502) {
        setErrorMessage('Bridge unreachable. Check the IP address and try again.')
      } else {
        setErrorMessage('Pairing failed. Please try again.')
      }
      setStep('error')
    }
  }

  if (step === 'checking') {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="glass rounded-2xl p-8 text-center max-w-md w-full">
          <div className="w-10 h-10 mx-auto mb-4 rounded-full border-2 border-hue-orange/40 border-t-hue-orange animate-spin" />
          <p className="text-sm text-muted-foreground">Checking bridge status...</p>
        </div>
      </div>
    )
  }

  if (step === 'unpaired') {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="glass rounded-2xl p-8 max-w-md w-full">
          <div className="text-center mb-6">
            <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-hue-orange/10 flex items-center justify-center">
              <div className="w-5 h-5 rounded-full bg-hue-orange/60 shadow-[0_0_12px_rgba(232,160,0,0.4)]" />
            </div>
            <h2 className="text-lg font-semibold text-foreground mb-1">Pair with Hue Bridge</h2>
            <p className="text-sm text-muted-foreground">Connect to your Philips Hue Bridge to get started</p>
          </div>

          <ol className="text-sm text-muted-foreground mb-6 space-y-2 list-decimal list-inside">
            <li>Press the <strong className="text-foreground">link button</strong> on your Hue Bridge</li>
            <li>Enter the bridge IP address below</li>
            <li>Click Pair within 30 seconds</li>
          </ol>

          <div className="flex gap-2">
            <input
              type="text"
              placeholder="192.168.1.x"
              value={bridgeIp}
              onChange={(e) => setBridgeIp(e.target.value)}
              className="flex-1"
            />
            <Button
              onClick={handlePair}
              disabled={!bridgeIp.trim()}
              className="bg-hue-orange/20 text-hue-amber border-hue-orange/30 hover:bg-hue-orange/30"
            >
              Pair
            </Button>
          </div>
        </div>
      </div>
    )
  }

  if (step === 'pairing') {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="glass rounded-2xl p-8 text-center max-w-md w-full">
          <div className="w-10 h-10 mx-auto mb-4 rounded-full border-2 border-hue-orange/40 border-t-hue-orange animate-spin" />
          <p className="text-sm text-muted-foreground">Pairing with bridge...</p>
        </div>
      </div>
    )
  }

  if (step === 'paired' && bridgeInfo) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="glass rounded-2xl p-8 max-w-md w-full">
          <div className="text-center mb-6">
            <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-green-500/10 flex items-center justify-center">
              <svg className="w-6 h-6 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-lg font-semibold text-foreground mb-1">Connected</h2>
            <p className="text-sm text-muted-foreground">
              Paired with <strong className="text-foreground">{bridgeInfo.bridge_name}</strong> at {bridgeInfo.bridge_ip}
            </p>
          </div>

          {configs.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                Entertainment Configurations
              </h3>
              <div className="space-y-2">
                {configs.map((cfg) => (
                  <div
                    key={cfg.id}
                    className="flex items-center justify-between rounded-xl px-4 py-3 bg-white/[0.03] border border-white/[0.06]"
                  >
                    <span className="text-sm font-medium text-foreground">{cfg.name}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">{cfg.channel_count} channels</span>
                      <span className={`text-[10px] px-2 py-0.5 rounded-full ${
                        cfg.status === 'active'
                          ? 'bg-green-500/10 text-green-400'
                          : 'bg-white/5 text-muted-foreground'
                      }`}>
                        {cfg.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="mt-6 pt-4 border-t border-white/[0.06]">
            {confirmDelete ? (
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm text-red-400">Remove this bridge?</p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="border-white/10"
                    onClick={() => setConfirmDelete(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    className="bg-red-500/20 text-red-400 border-red-500/30 hover:bg-red-500/30"
                    onClick={handleDelete}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            ) : (
              <Button
                variant="outline"
                size="sm"
                className="w-full border-red-500/20 text-red-400 hover:bg-red-500/10"
                onClick={() => setConfirmDelete(true)}
              >
                Delete Bridge
              </Button>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (step === 'error') {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="glass rounded-2xl p-8 max-w-md w-full text-center">
          <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-red-500/10 flex items-center justify-center">
            <svg className="w-6 h-6 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <p className="text-sm text-red-400 mb-4">{errorMessage}</p>
          <Button
            onClick={() => setStep('unpaired')}
            variant="outline"
            className="border-white/10"
          >
            Try Again
          </Button>
        </div>
      </div>
    )
  }

  return null
}
