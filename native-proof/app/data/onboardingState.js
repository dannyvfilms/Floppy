import { File, Paths } from 'expo-file-system';

const STATE_FILE = 'floppy-onboarding-state.json';

function stateFile() {
  return new File(Paths.document, STATE_FILE);
}

export async function readOnboardingState() {
  try {
    const file = stateFile();
    if (!file.exists) {
      return null;
    }
    const parsed = JSON.parse(await file.text());
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch (error) {
    return null;
  }
}

export async function writeOnboardingState(state) {
  try {
    const file = stateFile();
    if (!file.exists) {
      file.create({ intermediates: true });
    }
    await file.write(JSON.stringify(state));
  } catch (error) {
    // Storage is optional; the wizard keeps working without it.
  }
}
