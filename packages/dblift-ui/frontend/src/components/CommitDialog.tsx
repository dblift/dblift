import CommitForm, { type CommitFormProps } from "./CommitForm";
import Dialog from "./Dialog";

interface Props extends CommitFormProps {
  onClose: () => void;
}

export default function CommitDialog({ onClose, ...form }: Props) {
  return (
    <Dialog title="Commit" onClose={onClose}>
      <CommitForm className="dialog__body commit" {...form} />
    </Dialog>
  );
}
