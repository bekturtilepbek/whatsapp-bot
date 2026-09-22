"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  addProductMedia,
  createProduct,
  deleteProductMedia,
  productMediaUrl,
  updateProduct,
  type Product,
  type ProductInput,
  type ProductMedia,
} from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { MediaThumbnail } from "@/components/ui/MediaThumbnail";
import { NumberField } from "@/components/ui/NumberField";
import { Switch } from "@/components/ui/Switch";
import { Textarea } from "@/components/ui/Textarea";
import { useInvalidShake } from "@/lib/useInvalidShake";

// Пусто по умолчанию для <input accept>, чтобы фото и видео товара
// принимались одной формой (эталон V1 — одна смешанная галерея, FEATURES.md
// 4.4 ревизия), но не что попало.
const MEDIA_ACCEPT = "image/jpeg,image/png,image/webp,video/mp4";

interface ProductFormProps {
  botId: string;
  apiBaseUrl: string;
  /** Если задан — режим редактирования, иначе — создание нового товара. */
  product?: Product;
}

interface FormState {
  name: string;
  price: string;
  description: string;
  displayOverride: boolean;
  showName: boolean;
  showDescription: boolean;
  showPrice: boolean;
}

function initialState(product: Product | undefined): FormState {
  const hasOverride = !!product && Object.keys(product.display_custom).length > 0;
  return {
    name: product?.name ?? "",
    price: product?.price ?? "",
    description: product?.description ?? "",
    displayOverride: hasOverride,
    showName: product?.display_custom.show_name ?? true,
    showDescription: product?.display_custom.show_description ?? true,
    showPrice: product?.display_custom.show_price ?? true,
  };
}

function toInput(state: FormState): ProductInput {
  return {
    name: state.name.trim(),
    price: state.price.trim() === "" ? null : Number(state.price),
    // sku намеренно не отправляется из формы — поле убрано из UI кабинета
    // (артикул и так не показывается в карточке товара в WhatsApp, 4.5),
    // backend/БД-колонка сохранены нетронутыми.
    description: state.description.trim() === "" ? null : state.description.trim(),
    display_custom: state.displayOverride
      ? {
          show_name: state.showName,
          show_description: state.showDescription,
          show_price: state.showPrice,
        }
      : {},
  };
}

export function ProductForm({ botId, apiBaseUrl, product }: ProductFormProps) {
  const router = useRouter();
  const { showError, showSuccess } = useToast();
  const [state, setState] = useState<FormState>(() => initialState(product));
  const [newMedia, setNewMedia] = useState<File[]>([]);
  const [media, setMedia] = useState<ProductMedia[]>(product?.media ?? []);
  const [saving, setSaving] = useState(false);
  const [mediaBusy, setMediaBusy] = useState(false);
  const { shake, clear, isInvalid, shakeKey } = useInvalidShake();

  // PATCH на бэкенде мержит поля: null/пропуск значит «не трогать», а не
  // «очистить» (см. аналогичное поведение bots.image_prompt/pdf_prompt).
  // Значит стереть цену/артикул/описание обратно в пустоту через эту форму
  // нельзя — предупреждаем об этом в режиме редактирования там, где у товара
  // уже есть значение поля. Берём исходное значение из product, а не из
  // текущего state — подсказка не должна пропадать в момент, когда админ
  // как раз стирает поле (самый нужный момент её увидеть).
  const clearHint = "Поле нельзя очистить обратно — здесь можно только заменить значение на другое.";
  const showPriceHint = !!product && !!product.price && product.price.trim() !== "";
  const showDescriptionHint = !!product && !!product.description && product.description.trim() !== "";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (state.name.trim() === "") {
      showError("Название обязательно");
      shake(["name"]);
      return;
    }
    if (!product && newMedia.length === 0) {
      showError("Нужно хотя бы одно медиа");
      shake(["media"]);
      return;
    }
    setSaving(true);
    try {
      const input = toInput(state);
      if (product) {
        await updateProduct(apiBaseUrl, botId, product.id, input);
      } else {
        await createProduct(apiBaseUrl, botId, input, newMedia);
      }
      showSuccess("Товар сохранён");
      router.push(`/bots/${botId}/products`);
      router.refresh();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  const handleAddMedia = async (files: FileList | null) => {
    if (!product || !files || files.length === 0) {
      return;
    }
    setMediaBusy(true);
    try {
      const added = await addProductMedia(apiBaseUrl, botId, product.id, Array.from(files));
      setMedia((current) => [...current, ...added]);
      showSuccess("Медиа добавлено");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось добавить медиа");
    } finally {
      setMediaBusy(false);
    }
  };

  const handleDeleteMedia = async (mediaId: string) => {
    if (!product) {
      return;
    }
    setMediaBusy(true);
    try {
      await deleteProductMedia(apiBaseUrl, botId, product.id, mediaId);
      setMedia((current) => current.filter((m) => m.id !== mediaId));
      showSuccess("Медиа удалено");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось удалить медиа");
    } finally {
      setMediaBusy(false);
    }
  };

  return (
    // noValidate — та же причина, что и в BotSettingsForm: нативная
    // HTML5-валидация (required/min) тихо блокирует submit ДО нашей проверки.
    <form noValidate onSubmit={(e) => void handleSubmit(e)} className="max-w-xl space-y-5">
      <Card className="flex flex-col gap-4 p-5">
        <label
          className={`mb-0 block text-sm font-medium ${isInvalid("name") ? "text-danger" : "text-ink"}`}
        >
          <div
            key={isInvalid("name") ? `name-shake-${shakeKey}` : "name"}
            className={isInvalid("name") ? "animate-shake" : undefined}
          >
            Название <span className="text-danger">*</span>
            <Input
              type="text"
              value={state.name}
              invalid={isInvalid("name")}
              onChange={(e) => {
                setState({ ...state, name: e.target.value });
                clear("name");
              }}
              className="mt-1.5"
            />
          </div>
        </label>
        <div>
          <label className="mb-0 block text-sm font-medium text-ink">
            Цена
            <NumberField
              min={0}
              step={0.01}
              value={state.price}
              onChange={(e) => setState({ ...state, price: e.target.value })}
              className="mt-1.5"
            />
          </label>
          {showPriceHint && <p className="mt-1.5 text-xs text-ink-soft">{clearHint}</p>}
        </div>
        <div>
          <label className="mb-0 block text-sm font-medium text-ink">
            Описание
            <Textarea
              rows={4}
              value={state.description}
              onChange={(e) => setState({ ...state, description: e.target.value })}
              className="mt-1.5"
            />
          </label>
          {showDescriptionHint && <p className="mt-1.5 text-xs text-ink-soft">{clearHint}</p>}
        </div>
      </Card>

      <Card className="p-5">
        <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
          <Switch
            checked={state.displayOverride}
            onChange={(e) => setState({ ...state, displayOverride: e.target.checked })}
          />
          Переопределить вывод для этого товара
        </label>
        {state.displayOverride && (
          <fieldset className="mt-4 flex flex-col gap-3 border-0 p-0">
            <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
              <Switch
                checked={state.showName}
                onChange={(e) => setState({ ...state, showName: e.target.checked })}
              />
              Показывать название
            </label>
            <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
              <Switch
                checked={state.showDescription}
                onChange={(e) => setState({ ...state, showDescription: e.target.checked })}
              />
              Показывать описание
            </label>
            <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
              <Switch
                checked={state.showPrice}
                onChange={(e) => setState({ ...state, showPrice: e.target.checked })}
              />
              Показывать цену
            </label>
          </fieldset>
        )}
      </Card>

      {!product && (
        <Card className="p-5">
          <label
            className={`mb-0 block text-sm font-medium ${isInvalid("media") ? "text-danger" : "text-ink"}`}
          >
            <div
              key={isInvalid("media") ? `media-shake-${shakeKey}` : "media"}
              className={isInvalid("media") ? "animate-shake" : undefined}
            >
              Медиа <span className="text-danger">*</span>
              <input
                type="file"
                multiple
                accept={MEDIA_ACCEPT}
                onChange={(e) => {
                  setNewMedia(e.target.files ? Array.from(e.target.files) : []);
                  clear("media");
                }}
                className={`mt-1.5 block text-sm text-ink-soft file:mr-3 file:rounded-lg file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white hover:file:bg-accent-hover ${isInvalid("media") ? "rounded-lg outline outline-2 outline-danger" : ""}`}
              />
            </div>
          </label>
        </Card>
      )}

      {product && (
        <Card className="p-5">
          <h2 className="mb-4 text-[15px] font-semibold text-ink">Медиа</h2>
          <div className="flex flex-wrap gap-4">
            {media.map((item) => (
              <div key={item.id} className="w-24">
                <MediaThumbnail
                  src={productMediaUrl(apiBaseUrl, botId, product.id, item.id)}
                  mimeType={item.mime_type}
                  alt="Медиа товара"
                  className="h-24 w-24 rounded-lg object-cover"
                />
                <Button
                  type="button"
                  variant="danger"
                  className="mt-2 w-full justify-center"
                  disabled={mediaBusy || media.length <= 1}
                  title={media.length <= 1 ? "Нельзя удалить единственный элемент" : undefined}
                  onClick={() => void handleDeleteMedia(item.id)}
                >
                  Удалить
                </Button>
              </div>
            ))}
          </div>
          <label className="mb-0 mt-4 block text-sm font-medium text-ink">
            Добавить ещё
            <input
              type="file"
              multiple
              accept={MEDIA_ACCEPT}
              disabled={mediaBusy}
              onChange={(e) => void handleAddMedia(e.target.files)}
              className="mt-1.5 block text-sm text-ink-soft file:mr-3 file:rounded-lg file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white hover:file:bg-accent-hover disabled:opacity-60"
            />
          </label>
        </Card>
      )}

      <Button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </Button>
    </form>
  );
}
