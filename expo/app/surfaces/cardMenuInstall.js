import { setCardMenu } from '../../../frontend/ui/cardMenuHost';
import NativeCardMenu from './NativeCardMenu';

// Installs the system press-and-hold menu once, so every media card on every Expo screen has it.
export function installNativeCardMenu() {
  setCardMenu(NativeCardMenu);
}
